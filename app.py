from flask import Flask, request, jsonify
from datetime import datetime
from uuid import uuid4
import re
import os
from enum import Enum
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Enum as SQLEnum

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///payments.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Enums
class Currency(str, Enum):
    USD = "USD"
    UGX = "UGX"
    KES = "KES"

class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"

# SQLAlchemy Models
class Payment(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid4()))
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(SQLEnum(Currency), nullable=False)
    status = db.Column(SQLEnum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    description = db.Column(db.String, nullable=True)
    payment_metadata = db.Column(db.JSON, nullable=True)
    last_four = db.Column(db.String, nullable=False)

# Create the database tables
with app.app_context():
    db.create_all()

# Pydantic-like validation (using plain Python classes)
class CardDetails:
    def __init__(self, card_number, expiry_month, expiry_year, cvv, cardholder_name):
        self.card_number = card_number
        self.expiry_month = expiry_month
        self.expiry_year = expiry_year
        self.cvv = cvv
        self.cardholder_name = cardholder_name

    def validate(self):
        if not re.match(r'^\d{16}$', self.card_number):
            raise ValueError('Card number must be 16 digits')
        if not re.match(r'^(0[1-9]|1[0-2])$', self.expiry_month):
            raise ValueError('Invalid expiry month')
        if not re.match(r'^\d{4}$', self.expiry_year) or int(self.expiry_year) < datetime.now().year:
            raise ValueError('Invalid expiry year')
        if not re.match(r'^\d{3,4}$', self.cvv):
            raise ValueError('CVV must be 3 or 4 digits')

class PaymentRequest:
    def __init__(self, amount, currency, description=None, metadata=None, card_details=None):
        self.amount = amount
        self.currency = currency
        self.description = description
        self.metadata = metadata
        self.card_details = card_details

    def validate(self):
        if self.amount <= 0:
            raise ValueError('Amount must be greater than 0')
        if not isinstance(self.card_details, CardDetails):
            raise ValueError('Invalid card details')
        self.card_details.validate()

# Helper functions
def validate_api_key(api_key):
    """Validate the API key provided in the request header."""
    if api_key != os.getenv("API_KEY", "sk_test_123"):
        raise ValueError('Invalid API key')

def get_last_four_digits(card_number):
    """Extract the last four digits of the card number."""
    return card_number[-4:]

# Endpoints
@app.route('/v1/payments', methods=['POST'])
def create_payment():
    """Create a new payment."""
    api_key = request.headers.get('X-API-Key')
    try:
        validate_api_key(api_key)
        data = request.json

        # Validate payment request
        card_details = CardDetails(
            card_number=data['card_details']['card_number'],
            expiry_month=data['card_details']['expiry_month'],
            expiry_year=data['card_details']['expiry_year'],
            cvv=data['card_details']['cvv'],
            cardholder_name=data['card_details']['cardholder_name']
        )
        payment_request = PaymentRequest(
            amount=data['amount'],
            currency=data['currency'],
            description=data.get('description'),
            metadata=data.get('metadata'),
            card_details=card_details
        )
        payment_request.validate()

        # Simulate basic card validation
        if payment_request.card_details.card_number.startswith("4111"):
            status_value = PaymentStatus.SUCCEEDED
        else:
            status_value = PaymentStatus.FAILED
            return jsonify({"detail": "Card declined"}), 400

        # Create payment record
        payment = Payment(
            amount=payment_request.amount,
            currency=payment_request.currency,
            status=status_value,
            description=payment_request.description,
            payment_metadata=payment_request.metadata,
            last_four=get_last_four_digits(payment_request.card_details.card_number)
        )
        db.session.add(payment)
        db.session.commit()

        return jsonify({
            "id": payment.id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "created_at": payment.created_at.isoformat(),
            "description": payment.description,
            "metadata": payment.payment_metadata,
            "last_four": payment.last_four
        }), 201
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        print(e)
        return jsonify({"detail": "Internal server error"}), 500

@app.route('/v1/payments/<payment_id>', methods=['GET'])
def get_payment(payment_id):
    """Retrieve a payment by its ID."""
    api_key = request.headers.get('X-API-Key')
    try:
        validate_api_key(api_key)
        # Updated to use session.get()
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return jsonify({"detail": "Payment not found"}), 404

        return jsonify({
            "id": payment.id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "created_at": payment.created_at.isoformat(),
            "description": payment.description,
            "metadata": payment.payment_metadata,
            "last_four": payment.last_four
        }), 200
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        return jsonify({"detail": "Internal server error"}), 500

@app.route('/v1/payments/<payment_id>/refund', methods=['POST'])
def refund_payment(payment_id):
    """Refund a payment."""
    api_key = request.headers.get('X-API-Key')
    try:
        validate_api_key(api_key)
        data = request.json
        refund_amount = data.get('amount')

        # Updated to use session.get()
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return jsonify({"detail": "Payment not found"}), 404

        if payment.status != PaymentStatus.SUCCEEDED:
            return jsonify({"detail": "Payment cannot be refunded"}), 400

        if refund_amount and refund_amount > payment.amount:
            return jsonify({"detail": "Refund amount exceeds payment amount"}), 400

        payment.status = PaymentStatus.REFUNDED
        db.session.commit()

        return jsonify({
            "id": payment.id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "created_at": payment.created_at.isoformat(),
            "description": payment.description,
            "metadata": payment.payment_metadata,
            "last_four": payment.last_four
        }), 200
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"detail": "Internal server error"}), 500

@app.route('/v1/payments', methods=['GET'])
def list_payments():
    """List all payments with pagination."""
    api_key = request.headers.get('X-API-Key')
    try:
        validate_api_key(api_key)
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))

        # Updated to use select()
        payments = db.session.execute(
            db.select(Payment).offset(offset).limit(limit)
        ).scalars().all()

        return jsonify([
            {
                "id": payment.id,
                "amount": payment.amount,
                "currency": payment.currency,
                "status": payment.status,
                "created_at": payment.created_at.isoformat(),
                "description": payment.description,
                "metadata": payment.payment_metadata,
                "last_four": payment.last_four
            }
            for payment in payments
        ]), 200
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        return jsonify({"detail": "Internal server error"}), 500

# Run the app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
