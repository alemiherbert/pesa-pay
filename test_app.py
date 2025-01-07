import pytest
from datetime import datetime
import json
from app import app, db, Payment, PaymentStatus, Currency

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['API_KEY'] = 'sk_test_123'
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.drop_all()

@pytest.fixture
def valid_payment_data():
    return {
        "amount": 1000.00,
        "currency": "USD",
        "description": "Test payment",
        "metadata": {"order_id": "12345"},
        "card_details": {
            "card_number": "4111111111111111",
            "expiry_month": "12",
            "expiry_year": str(datetime.now().year + 1),
            "cvv": "123",
            "cardholder_name": "Test User"
        }
    }

@pytest.fixture
def auth_headers():
    return {"X-API-Key": "sk_test_123"}

def test_create_payment_success(client, valid_payment_data, auth_headers):
    response = client.post('/v1/payments', 
                         json=valid_payment_data,
                         headers=auth_headers)
    
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data["amount"] == 1000.00
    assert data["currency"] == "USD"
    assert data["status"] == "completed"
    assert data["last_four"] == "1111"
    assert data["description"] == "Test payment"
    assert data["metadata"] == {"order_id": "12345"}

def test_create_payment_invalid_card(client, valid_payment_data, auth_headers):
    valid_payment_data["card_details"]["card_number"] = "5555555555554444"
    
    response = client.post('/v1/payments', 
                         json=valid_payment_data,
                         headers=auth_headers)
    
    assert response.status_code == 400
    assert json.loads(response.data)["detail"] == "Card declined"

def test_create_payment_invalid_api_key(client, valid_payment_data):
    response = client.post('/v1/payments', 
                         json=valid_payment_data,
                         headers={"X-API-Key": "invalid_key"})
    
    assert response.status_code == 400
    assert "Invalid API key" in json.loads(response.data)["detail"]

def test_create_payment_invalid_amount(client, valid_payment_data, auth_headers):
    valid_payment_data["amount"] = -100
    
    response = client.post('/v1/payments', 
                         json=valid_payment_data,
                         headers=auth_headers)
    
    assert response.status_code == 400
    assert "Amount must be greater than 0" in json.loads(response.data)["detail"]

def test_get_payment_success(client, valid_payment_data, auth_headers):
    # First create a payment
    create_response = client.post('/v1/payments', 
                                json=valid_payment_data,
                                headers=auth_headers)
    payment_id = json.loads(create_response.data)["id"]
    
    # Then retrieve it
    response = client.get(f'/v1/payments/{payment_id}',
                         headers=auth_headers)
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["id"] == payment_id
    assert data["amount"] == 1000.00
    assert data["status"] == "completed"

def test_get_payment_not_found(client, auth_headers):
    response = client.get('/v1/payments/nonexistent-id',
                         headers=auth_headers)
    
    assert response.status_code == 404
    assert json.loads(response.data)["detail"] == "Payment not found"

def test_refund_payment_success(client, valid_payment_data, auth_headers):
    # First create a payment
    create_response = client.post('/v1/payments', 
                                json=valid_payment_data,
                                headers=auth_headers)
    payment_id = json.loads(create_response.data)["id"]
    
    # Then refund it
    response = client.post(f'/v1/payments/{payment_id}/refund',
                          json={"amount": 1000.00},
                          headers=auth_headers)
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "refunded"

def test_refund_payment_invalid_amount(client, valid_payment_data, auth_headers):
    # First create a payment
    create_response = client.post('/v1/payments', 
                                json=valid_payment_data,
                                headers=auth_headers)
    payment_id = json.loads(create_response.data)["id"]
    
    # Try to refund more than the payment amount
    response = client.post(f'/v1/payments/{payment_id}/refund',
                          json={"amount": 2000.00},
                          headers=auth_headers)
    
    assert response.status_code == 400
    assert "Refund amount exceeds payment amount" in json.loads(response.data)["detail"]

def test_list_payments(client, valid_payment_data, auth_headers):
    # Create multiple payments
    for _ in range(3):
        client.post('/v1/payments', 
                   json=valid_payment_data,
                   headers=auth_headers)
    
    # Test pagination
    response = client.get('/v1/payments?limit=2&offset=0',
                         headers=auth_headers)
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 2
    
    # Test offset
    response = client.get('/v1/payments?limit=2&offset=2',
                         headers=auth_headers)
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 1

def test_card_validation():
    from app import CardDetails
    
    with pytest.raises(ValueError):
        # Test invalid card number
        card = CardDetails("123", "12", str(datetime.now().year + 1), "123", "Test User")
        card.validate()
    
    with pytest.raises(ValueError):
        # Test invalid expiry month
        card = CardDetails("4111111111111111", "13", str(datetime.now().year + 1), "123", "Test User")
        card.validate()
    
    with pytest.raises(ValueError):
        # Test expired year
        card = CardDetails("4111111111111111", "12", "2020", "123", "Test User")
        card.validate()
    
    with pytest.raises(ValueError):
        # Test invalid CVV
        card = CardDetails("4111111111111111", "12", str(datetime.now().year + 1), "12345", "Test User")
        card.validate()

def test_payment_model():
    with app.app_context():
        payment = Payment(
            amount=1000.00,
            currency=Currency.USD,
            status=PaymentStatus.COMPLETED,
            description="Test payment",
            payment_metadata={"order_id": "12345"},
            last_four="1111"
        )
        
        assert payment.amount == 1000.00
        assert payment.currency == Currency.USD
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.description == "Test payment"
        assert payment.payment_metadata == {"order_id": "12345"}
        assert payment.last_four == "1111"
