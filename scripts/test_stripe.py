import stripe
import os
from dotenv import load_dotenv

# Load settings from the salonos .env
load_dotenv(r"C:\Users\syfsy\projekty\salonos\.env")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

def test_stripe_connection():
    print("--- Senior IT: Stripe Connection Test ---")
    try:
        # Try to create a dummy product to test WRITE permissions
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'pln',
                    'product_data': {'name': 'Testowy Zadatek - Danex'},
                    'unit_amount': 2000, # 20.00 PLN
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='http://localhost:8000/success',
            cancel_url='http://localhost:8000/cancel',
        )
        print("[SUCCESS] Link to Stripe generated successfully!")
        print(f"URL: {session.url}")
        print("\nTwój system finansowy jest AKTYWNY.")
    except Exception as e:
        print(f"[FAIL] Stripe error: {str(e)}")
        print("\nSprawdź czy klucz w .env jest poprawny.")

if __name__ == "__main__":
    test_stripe_connection()
