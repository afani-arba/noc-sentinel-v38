import requests
import sys
import json
import uuid
from datetime import datetime

class MikroTikMonitorTester:
    def __init__(self, base_url="https://ros-dashboard-1.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_result(self, test_name, success, message="", response_data=None):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {test_name}: PASSED - {message}")
        else:
            print(f"❌ {test_name}: FAILED - {message}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "message": message,
            "response_data": response_data[:100] if isinstance(response_data, str) and len(response_data) > 100 else response_data
        })

    def run_test(self, name, method, endpoint, expected_status, data=None, check_response=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {'Content-Type': 'application/json'}
        
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers, timeout=10)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=10)
            else:
                self.log_result(name, False, f"Unsupported method: {method}")
                return False, {}

            success = response.status_code == expected_status
            
            try:
                response_json = response.json() if response.text else {}
            except:
                response_json = {"raw_response": response.text}
            
            if success:
                msg = f"Status: {response.status_code}"
                if check_response and callable(check_response):
                    additional_check = check_response(response_json)
                    if not additional_check[0]:
                        success = False
                        msg = f"Status OK but response check failed: {additional_check[1]}"
                    else:
                        msg += f" | {additional_check[1]}"
            else:
                msg = f"Expected {expected_status}, got {response.status_code}"
                if response.text:
                    try:
                        error_detail = response.json().get('detail', response.text[:100])
                        msg += f" | {error_detail}"
                    except:
                        msg += f" | {response.text[:100]}"

            self.log_result(name, success, msg, response_json)
            return success, response_json

        except requests.exceptions.RequestException as e:
            self.log_result(name, False, f"Request error: {str(e)}")
            return False, {}
        except Exception as e:
            self.log_result(name, False, f"Unexpected error: {str(e)}")
            return False, {}

    def test_login(self):
        """Test admin login"""
        success, response = self.run_test(
            "Admin Login",
            "POST",
            "auth/login",
            200,
            data={"username": "admin", "password": "admin123"},
            check_response=lambda r: (
                'token' in r and 'user' in r,
                f"Token present: {'token' in r}, User present: {'user' in r}"
            )
        )
        
        if success and 'token' in response:
            self.token = response['token']
            return True
        return False

    def test_auth_me(self):
        """Test auth/me endpoint with token"""
        return self.run_test(
            "Auth Me",
            "GET", 
            "auth/me",
            200,
            check_response=lambda r: (
                'username' in r and 'role' in r,
                f"Username: {r.get('username', 'missing')}, Role: {r.get('role', 'missing')}"
            )
        )

    def test_dashboard_stats(self):
        """Test dashboard stats"""
        success, response = self.run_test(
            "Dashboard Stats",
            "GET",
            "dashboard/stats", 
            200,
            check_response=lambda r: (
                all(key in r for key in ['pppoe', 'hotspot', 'devices', 'traffic_data', 'system_health', 'alerts']),
                f"Keys present: {list(r.keys())[:5]}..."
            )
        )
        return success

    def test_pppoe_users_crud(self):
        """Test PPPoE users CRUD operations"""
        # List users
        success, users_list = self.run_test(
            "List PPPoE Users",
            "GET",
            "pppoe-users",
            200,
            check_response=lambda r: (
                isinstance(r, list) and len(r) > 0,
                f"Found {len(r) if isinstance(r, list) else 'invalid'} users"
            )
        )
        
        if not success:
            return False

        # Create new user
        test_user = {
            "username": f"test_pppoe_{uuid.uuid4().hex[:8]}",
            "password": "testpass123",
            "profile": "10Mbps",
            "service": "pppoe",
            "ip_address": "10.0.1.100",
            "mac_address": "00:11:22:33:44:55",
            "comment": "Test user created by automation"
        }
        
        success, created_user = self.run_test(
            "Create PPPoE User",
            "POST",
            "pppoe-users",
            201,
            data=test_user,
            check_response=lambda r: (
                'id' in r and r.get('username') == test_user['username'],
                f"User created with ID: {r.get('id', 'missing')}"
            )
        )
        
        if not success:
            return False

        user_id = created_user.get('id')
        
        # Update user
        update_data = {"comment": "Updated by automation test", "status": "disabled"}
        success, updated_user = self.run_test(
            "Update PPPoE User", 
            "PUT",
            f"pppoe-users/{user_id}",
            200,
            data=update_data,
            check_response=lambda r: (
                r.get('comment') == update_data['comment'] and r.get('status') == update_data['status'],
                f"Comment: {r.get('comment', 'missing')}, Status: {r.get('status', 'missing')}"
            )
        )
        
        # Search users
        search_success, _ = self.run_test(
            "Search PPPoE Users",
            "GET",
            f"pppoe-users?search={test_user['username'][:8]}",
            200,
            check_response=lambda r: (
                isinstance(r, list) and len(r) >= 1,
                f"Search returned {len(r) if isinstance(r, list) else 'invalid'} results"
            )
        )
        
        return success and search_success

    def test_hotspot_users_crud(self):
        """Test Hotspot users CRUD operations"""
        # List users
        success, users_list = self.run_test(
            "List Hotspot Users",
            "GET",
            "hotspot-users",
            200,
            check_response=lambda r: (
                isinstance(r, list) and len(r) > 0,
                f"Found {len(r) if isinstance(r, list) else 'invalid'} users"
            )
        )
        
        if not success:
            return False

        # Create new user
        test_user = {
            "username": f"test_hotspot_{uuid.uuid4().hex[:8]}",
            "password": "hspass123",
            "profile": "1hour",
            "server": "hotspot1",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "limit_uptime": "1h",
            "limit_bytes_total": "100M",
            "comment": "Test hotspot user"
        }
        
        success, created_user = self.run_test(
            "Create Hotspot User",
            "POST",
            "hotspot-users",
            201,
            data=test_user,
            check_response=lambda r: (
                'id' in r and r.get('username') == test_user['username'],
                f"User created with ID: {r.get('id', 'missing')}"
            )
        )
        
        if not success:
            return False

        user_id = created_user.get('id')
        
        # Update user
        update_data = {"comment": "Updated hotspot user", "status": "expired"}
        success, _ = self.run_test(
            "Update Hotspot User",
            "PUT", 
            f"hotspot-users/{user_id}",
            200,
            data=update_data,
            check_response=lambda r: (
                r.get('comment') == update_data['comment'],
                f"Updated comment: {r.get('comment', 'missing')}"
            )
        )
        
        return success

    def test_devices_management(self):
        """Test device management"""
        # List devices
        success, devices = self.run_test(
            "List Devices",
            "GET",
            "devices",
            200,
            check_response=lambda r: (
                isinstance(r, list) and len(r) > 0,
                f"Found {len(r) if isinstance(r, list) else 'invalid'} devices"
            )
        )
        
        if not success:
            return False

        # Add new device
        test_device = {
            "name": f"Test-Router-{uuid.uuid4().hex[:8]}",
            "ip_address": "192.168.1.99",
            "port": 8728,
            "username": "admin",
            "password": "testpass",
            "description": "Test device for automation"
        }
        
        success, created_device = self.run_test(
            "Add Device",
            "POST",
            "devices",
            201,
            data=test_device,
            check_response=lambda r: (
                'id' in r and r.get('name') == test_device['name'],
                f"Device created: {r.get('name', 'missing')}"
            )
        )
        
        if not success:
            return False

        device_id = created_device.get('id')
        
        # Delete device
        success, _ = self.run_test(
            "Delete Device",
            "DELETE",
            f"devices/{device_id}",
            200,
            check_response=lambda r: (
                'message' in r,
                f"Delete response: {r.get('message', 'missing')}"
            )
        )
        
        return success

    def test_reports_generation(self):
        """Test report generation"""
        for period in ["daily", "weekly", "monthly"]:
            success, report = self.run_test(
                f"Generate {period.capitalize()} Report",
                "POST",
                "reports/generate",
                200,
                data={"period": period},
                check_response=lambda r: (
                    all(key in r for key in ['label', 'period', 'summary', 'traffic_trend']),
                    f"Report period: {r.get('period', 'missing')}, Label: {r.get('label', 'missing')}"
                )
            )
            if not success:
                return False
        return True

    def test_admin_users(self):
        """Test admin user management"""
        # List admin users
        success, users = self.run_test(
            "List Admin Users",
            "GET",
            "admin/users",
            200,
            check_response=lambda r: (
                isinstance(r, list) and len(r) > 0,
                f"Found {len(r) if isinstance(r, list) else 'invalid'} admin users"
            )
        )
        
        if not success:
            return False

        # Create new admin user  
        test_admin = {
            "username": f"test_admin_{uuid.uuid4().hex[:8]}",
            "password": "admintest123",
            "full_name": "Test Administrator", 
            "role": "user"
        }
        
        success, created_admin = self.run_test(
            "Create Admin User",
            "POST",
            "admin/users",
            201,
            data=test_admin,
            check_response=lambda r: (
                'id' in r and r.get('username') == test_admin['username'],
                f"Admin created: {r.get('username', 'missing')}"
            )
        )
        
        if not success:
            return False

        admin_id = created_admin.get('id')
        
        # Update admin user
        update_data = {"full_name": "Updated Test Admin", "role": "viewer"}
        success, _ = self.run_test(
            "Update Admin User",
            "PUT",
            f"admin/users/{admin_id}",
            200,
            data=update_data,
            check_response=lambda r: (
                r.get('full_name') == update_data['full_name'] and r.get('role') == update_data['role'],
                f"Updated name: {r.get('full_name', 'missing')}, role: {r.get('role', 'missing')}"
            )
        )
        
        return success

    def run_all_tests(self):
        """Run complete test suite"""
        print("=" * 80)
        print("🚀 STARTING MIKROTIK MONITORING TOOL API TESTS")
        print("=" * 80)
        
        # Authentication tests
        if not self.test_login():
            print("\n❌ LOGIN FAILED - Cannot proceed with authenticated tests")
            return False
            
        self.test_auth_me()
        
        # Core functionality tests
        self.test_dashboard_stats()
        self.test_pppoe_users_crud()
        self.test_hotspot_users_crud()
        self.test_devices_management()
        self.test_reports_generation()
        self.test_admin_users()
        
        # Results summary
        print("\n" + "=" * 80)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 80)
        print(f"Total Tests: {self.tests_run}")
        print(f"Passed: {self.tests_passed}")
        print(f"Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%")
        
        if self.tests_passed == self.tests_run:
            print("🎉 ALL TESTS PASSED!")
            return True
        else:
            print("⚠️  SOME TESTS FAILED")
            print("\nFailed tests:")
            for result in self.test_results:
                if not result['success']:
                    print(f"  - {result['test']}: {result['message']}")
            return False

def main():
    tester = MikroTikMonitorTester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())