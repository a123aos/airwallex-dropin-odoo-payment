/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { PaymentPostProcessing } from '@payment/interactions/post_processing';


patch(PaymentPostProcessing.prototype, {
    start() {
        // Airwallex Bank Transfer is asynchronous. Once Airwallex has shown
        // the transfer instructions, the customer may complete the payment
        // later (even after leaving the website). The Airwallex webhook is
        // the source of truth for the final transaction state, so do not keep
        // the browser polling Odoo indefinitely for this payment method.
        if (this.el.dataset.airwallexBankTransferPending === '1') {
            const heading = this.el.querySelector('#o_payment_status_message h5');
            const message = this.el.querySelector('#o_payment_status_message p.mb-0');
            const skip = this.el.querySelector('a.alert-link');
            const icon = this.el.querySelector('#o_payment_status_icon i');

            if (heading) {
                heading.textContent = 'Bank transfer pending';
            }

            // The native template renders the provider status message as a
            // paragraph. Replace only its text while keeping Odoo's native
            // payment status page structure intact.
            if (message) {
                message.textContent =
                    'Please complete your bank transfer using the payment instructions provided. '
                    + 'Your order will be confirmed automatically once we receive your payment.';
            }

            if (skip) {
                skip.remove();
            }

            if (icon) {
                icon.classList.remove('fa-cog', 'fa-spin');
                icon.classList.add('fa-info-circle');
            }

            return;
        }

        super.start(...arguments);
    },
});
