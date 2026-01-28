from __future__ import annotations
import os

def get_tokusho() -> dict:
    return {
        "seller": os.getenv("SELLER_NAME", "Equine Vet Synapse"),
        "representative": os.getenv("REPRESENTATIVE_NAME", "上手健太郎"),
        "email": os.getenv("CONTACT_EMAIL", "equinevet.owners@gmail.com"),
        "site": os.getenv("BUSINESS_SITE", "https://www.minamisoma-vet.com/"),
        "address": os.getenv("BUSINESS_ADDRESS", "（所在地を環境変数 BUSINESS_ADDRESS に設定してください）"),
        "price": os.getenv("PRICE_TEXT", "月額 550円（税込）"),
        "payment": os.getenv("PAYMENT_TEXT", "銀行振込 / PayPal / Stripe / PayPay（順次対応）"),
        "delivery": os.getenv("DELIVERY_TEXT", "決済完了後、直ちに利用可能"),
        "refund": os.getenv("REFUND_TEXT", "デジタルサービスの性質上、原則返金不可（法令に基づく場合を除く）"),
    }

def get_privacy_meta() -> dict:
    return {
        "seller": os.getenv("SELLER_NAME", "Equine Vet Synapse"),
        "email": os.getenv("CONTACT_EMAIL", "equinevet.owners@gmail.com"),
        "site": os.getenv("BUSINESS_SITE", "https://www.minamisoma-vet.com/"),
        "address": os.getenv("BUSINESS_ADDRESS", "（所在地を環境変数 BUSINESS_ADDRESS に設定してください）"),
    }
