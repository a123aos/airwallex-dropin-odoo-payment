# -*- coding: utf-8 -*-

# 1. API 端點：區分測試與生產環境
API_ENDPOINT = {
    'test': 'https://api-demo.airwallex.com/api/v1',
    'prod': 'https://api.airwallex.com/api/v1',
}

# 2. 認領清單：目前專注於信用卡 (Card) 原生元件
DEFAULT_PAYMENT_METHOD_CODES = {
    'card',
}

# 3. 狀態映射 (Airwallex -> Odoo)
# 參考：https://www.airwallex.com/docs/payments/reference/payment-statuses
PAYMENT_STATUS_MAPPING = {
    # 待處理與風險審核狀態
    'REQUIRES_PAYMENT_METHOD': 'pending',
    'REQUIRES_CUSTOMER_ACTION': 'pending',
    'PENDING': 'pending',
    'PENDING_REVIEW': 'pending',    # 重要：當觸發風險審核時，維持 pending
    
    # 已授權 (尚未請款)
    'REQUIRES_CAPTURE': 'authorized',
    
    # 成功狀態
    'SUCCEEDED': 'done',
    
    # 取消與失敗狀態
    'CANCELLED': 'cancel',
    'FAILED': 'error',
    'EXPIRED': 'error',
}

# 退款狀態映射 (根據 Airwallex 2025-02-14 最新規範)
# 參考：https://www.airwallex.com/docs/payments/payment-operations/manage-payments/refunds#refund-statuses
REFUND_STATUS_MAPPING = {
    'RECEIVED': 'pending',
    'ACCEPTED': 'pending',   # 已接受，但資金尚未完成結算
    'SETTLED': 'done',       # 終端成功狀態：資金已完成結算退回 (取代已棄用的 SUCCEEDED)
    'FAILED': 'error',
}

# 4. 支援的 Webhook 事件類型
# 這些事件將觸發 Controller 的 _process 方法。
# 我們保留了 .updated 與 .pending_review 以確保狀態變更不會被遺漏。
SUPPORTED_WEBHOOK_EVENTS = [
    # --- Payment Intent 事件 ---
    'payment_intent.created',             # 初始建立，通常為 REQUIRES_PAYMENT_METHOD
    'payment_intent.updated',             # 任何屬性更新時觸發，作為狀態同步的保險
    'payment_intent.requires_payment_method',
    'payment_intent.requires_customer_action',
    'payment_intent.requires_capture',    # 觸發 Odoo 設為 authorized
    'payment_intent.pending',
    'payment_intent.pending_review',      # 觸發 Odoo 設為 pending (風險審核)
    'payment_intent.succeeded',           # 觸發 Odoo 設為 done
    'payment_intent.cancelled',           # 觸發 Odoo 設為 cancel

    # --- Payment Attempt 事件 (記錄支付嘗試的詳細失敗) ---
    'payment_attempt.authorized',
    'payment_attempt.authorization_failed',
    'payment_attempt.capture_failed',
    'payment_attempt.failed_to_process',
    'payment_attempt.expired',

    # --- Refund 事件 (退款流程) ---
    'refund.received',
    'refund.accepted', 
    'refund.settled',                     # 官方最新事件名稱
    'refund.failed',
]

# 5. 業務標籤
INSTALLMENT_FEE_LABEL = "Installment Fee"