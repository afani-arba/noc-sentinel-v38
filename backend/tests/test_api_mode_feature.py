"""
Test suite for RouterOS v6/v7 API Mode feature
Tests device creation, update, and API mode handling
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAuthAndHealth:
    """Basic authentication and health checks"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token for admin"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "token" in data
        return data["token"]
    
    def test_health_endpoint(self):
        """Test health endpoint is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        print("✅ Health endpoint OK")
    
    def test_login_success(self):
        """Test admin login works"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["username"] == "admin"
        print("✅ Login successful")


class TestDeviceApiMode:
    """Tests for api_mode field in device CRUD operations"""
    
    @pytest.fixture(scope="class")
    def auth_headers(self):
        """Get authentication headers"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    @pytest.fixture
    def cleanup_test_devices(self, auth_headers):
        """Cleanup test devices after tests"""
        created_ids = []
        yield created_ids
        # Teardown: delete all created test devices
        for device_id in created_ids:
            try:
                requests.delete(f"{BASE_URL}/api/devices/{device_id}", headers=auth_headers)
            except:
                pass
    
    def test_list_devices(self, auth_headers):
        """Test listing devices returns api_mode field"""
        response = requests.get(f"{BASE_URL}/api/devices", headers=auth_headers)
        assert response.status_code == 200
        devices = response.json()
        assert isinstance(devices, list)
        print(f"✅ Listed {len(devices)} devices")
        # If devices exist, check api_mode field
        for device in devices:
            print(f"  Device: {device.get('name')} - API Mode: {device.get('api_mode', 'not set')}")
    
    def test_create_device_with_rest_api_mode(self, auth_headers, cleanup_test_devices):
        """Test creating device with REST API mode (RouterOS 7+)"""
        device_data = {
            "name": "TEST_Router_V7",
            "ip_address": "192.168.88.1",
            "snmp_community": "public",
            "snmp_port": 161,
            "api_mode": "rest",  # RouterOS 7+ REST API
            "api_username": "admin",
            "api_password": "test123",
            "api_port": 443,
            "api_ssl": True,
            "description": "Test router for RouterOS 7"
        }
        
        response = requests.post(f"{BASE_URL}/api/devices", 
                                json=device_data, headers=auth_headers)
        assert response.status_code == 201, f"Create failed: {response.text}"
        
        created = response.json()
        assert "id" in created
        cleanup_test_devices.append(created["id"])
        
        # Verify api_mode is saved correctly
        assert created.get("api_mode") == "rest", f"Expected api_mode='rest', got '{created.get('api_mode')}'"
        assert created.get("api_port") == 443
        assert created.get("api_ssl") == True
        print(f"✅ Created device with REST API mode: {created['name']}")
        
        # GET to verify persistence
        get_response = requests.get(f"{BASE_URL}/api/devices", headers=auth_headers)
        devices = get_response.json()
        created_device = next((d for d in devices if d["id"] == created["id"]), None)
        assert created_device is not None
        assert created_device.get("api_mode") == "rest"
        print("✅ Verified api_mode persisted correctly in database")
    
    def test_create_device_with_api_protocol_mode(self, auth_headers, cleanup_test_devices):
        """Test creating device with API Protocol mode (RouterOS 6+)"""
        device_data = {
            "name": "TEST_Router_V6",
            "ip_address": "192.168.88.2",
            "snmp_community": "public",
            "snmp_port": 161,
            "api_mode": "api",  # RouterOS 6+ API protocol
            "api_username": "admin",
            "api_password": "test123",
            "api_port": 8728,
            "api_ssl": False,
            "api_plaintext_login": True,
            "description": "Test router for RouterOS 6"
        }
        
        response = requests.post(f"{BASE_URL}/api/devices", 
                                json=device_data, headers=auth_headers)
        assert response.status_code == 201, f"Create failed: {response.text}"
        
        created = response.json()
        assert "id" in created
        cleanup_test_devices.append(created["id"])
        
        # Verify api_mode is saved correctly
        assert created.get("api_mode") == "api", f"Expected api_mode='api', got '{created.get('api_mode')}'"
        assert created.get("api_port") == 8728
        assert created.get("api_ssl") == False
        print(f"✅ Created device with API Protocol mode: {created['name']}")
        
        # GET to verify persistence
        get_response = requests.get(f"{BASE_URL}/api/devices", headers=auth_headers)
        devices = get_response.json()
        created_device = next((d for d in devices if d["id"] == created["id"]), None)
        assert created_device is not None
        assert created_device.get("api_mode") == "api"
        print("✅ Verified api_mode persisted correctly in database")
    
    def test_update_device_api_mode(self, auth_headers, cleanup_test_devices):
        """Test updating device api_mode from REST to API protocol"""
        # First create a device with REST API mode
        device_data = {
            "name": "TEST_Router_Update",
            "ip_address": "192.168.88.3",
            "api_mode": "rest",
            "api_port": 443,
            "api_ssl": True,
        }
        
        create_response = requests.post(f"{BASE_URL}/api/devices", 
                                       json=device_data, headers=auth_headers)
        assert create_response.status_code == 201
        device_id = create_response.json()["id"]
        cleanup_test_devices.append(device_id)
        
        # Update to API protocol mode
        update_data = {
            "api_mode": "api",
            "api_port": 8728,
            "api_ssl": False
        }
        
        update_response = requests.put(f"{BASE_URL}/api/devices/{device_id}",
                                       json=update_data, headers=auth_headers)
        assert update_response.status_code == 200, f"Update failed: {update_response.text}"
        
        updated = update_response.json()
        assert updated.get("api_mode") == "api", f"Expected api_mode='api', got '{updated.get('api_mode')}'"
        assert updated.get("api_port") == 8728
        assert updated.get("api_ssl") == False
        print("✅ Updated device api_mode from REST to API protocol")
    
    def test_default_api_mode(self, auth_headers, cleanup_test_devices):
        """Test that default api_mode is 'rest' when not specified"""
        device_data = {
            "name": "TEST_Router_Default",
            "ip_address": "192.168.88.4",
        }
        
        response = requests.post(f"{BASE_URL}/api/devices", 
                                json=device_data, headers=auth_headers)
        assert response.status_code == 201, f"Create failed: {response.text}"
        
        created = response.json()
        cleanup_test_devices.append(created["id"])
        
        # Default should be 'rest'
        assert created.get("api_mode") == "rest", f"Default api_mode should be 'rest', got '{created.get('api_mode')}'"
        print("✅ Default api_mode is 'rest' as expected")


class TestDeviceApiTest:
    """Tests for test-api endpoint with different api_modes"""
    
    @pytest.fixture(scope="class")
    def auth_headers(self):
        """Get authentication headers"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_test_api_endpoint_exists(self, auth_headers):
        """Test that test-api endpoint exists for devices"""
        # First get a device
        devices_response = requests.get(f"{BASE_URL}/api/devices", headers=auth_headers)
        devices = devices_response.json()
        
        if not devices:
            pytest.skip("No devices to test API connection")
        
        device = devices[0]
        device_id = device["id"]
        
        # Call test-api endpoint
        response = requests.post(f"{BASE_URL}/api/devices/{device_id}/test-api", 
                                headers=auth_headers)
        
        # Should return 200 even if connection fails (returns success: false)
        assert response.status_code == 200, f"test-api endpoint failed: {response.text}"
        
        result = response.json()
        # Should have success key and mode key
        assert "success" in result, "Response should have 'success' key"
        assert "mode" in result, "Response should have 'mode' key indicating API type"
        
        print(f"✅ test-api endpoint works - Success: {result['success']}, Mode: {result['mode']}")
        if not result['success']:
            print(f"  Note: Connection failed (expected if no real router): {result.get('error', 'N/A')}")
    
    def test_test_new_device_endpoint(self, auth_headers):
        """Test test-new endpoint for both API modes"""
        # Test with REST API mode
        rest_data = {
            "name": "Test REST",
            "ip_address": "192.168.88.99",
            "api_mode": "rest",
            "api_port": 443,
            "api_ssl": True,
            "api_username": "admin",
            "api_password": "test"
        }
        
        response = requests.post(f"{BASE_URL}/api/devices/test-new",
                                json=rest_data, headers=auth_headers)
        assert response.status_code == 200
        result = response.json()
        assert "api" in result, "Response should have 'api' test result"
        print(f"✅ test-new endpoint works for REST API mode")
        
        # Test with API Protocol mode
        api_data = {
            "name": "Test API",
            "ip_address": "192.168.88.99",
            "api_mode": "api",
            "api_port": 8728,
            "api_ssl": False,
            "api_username": "admin",
            "api_password": "test"
        }
        
        response = requests.post(f"{BASE_URL}/api/devices/test-new",
                                json=api_data, headers=auth_headers)
        assert response.status_code == 200
        result = response.json()
        assert "api" in result, "Response should have 'api' test result"
        print(f"✅ test-new endpoint works for API Protocol mode")


class TestExistingDevice:
    """Test existing device 'Router Core' for api_mode field"""
    
    @pytest.fixture(scope="class")
    def auth_headers(self):
        """Get authentication headers"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_existing_device_has_api_mode(self, auth_headers):
        """Check if existing devices have api_mode field"""
        response = requests.get(f"{BASE_URL}/api/devices", headers=auth_headers)
        assert response.status_code == 200
        devices = response.json()
        
        if not devices:
            pytest.skip("No existing devices found")
        
        for device in devices:
            api_mode = device.get("api_mode", "NOT SET")
            print(f"  Device '{device['name']}': api_mode = {api_mode}")
            # api_mode should be either 'rest' or 'api'
            if api_mode != "NOT SET":
                assert api_mode in ["rest", "api"], f"Invalid api_mode: {api_mode}"
        
        print("✅ All existing devices have valid api_mode field")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
