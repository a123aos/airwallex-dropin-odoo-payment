/**
 * Airwallex Bank Transfer is asynchronous: once the customer has received
 * the transfer instructions, the browser does not need to keep polling
 * Odoo while the customer completes the transfer later.
 *
 * This module intentionally does not change the transaction state. The
 * Airwallex webhook remains the source of truth and changes the transaction
 * from pending to done when the transfer is actually received.
 */

/**
 * Return whether the current payment flow is an Airwallex Bank Transfer.
 *
 * The payment provider/method information is exposed by the Odoo payment
 * form. Keep this helper deliberately defensive so other payment methods are
 * untouched if the relevant data is not available.
 */
export function isAirwallexBankTransfer(paymentContext) {
    if (!paymentContext) {
        return false;
    }

    const providerCode = paymentContext.providerCode || paymentContext.provider_code;
    const paymentMethodCode = paymentContext.paymentMethodCode || paymentContext.payment_method_code;

    return providerCode === 'airwallex' && paymentMethodCode === 'bank_transfer';
}
