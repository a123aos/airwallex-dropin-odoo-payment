/** @odoo-module **/

import { loadJS } from '@web/core/assets';
import { _t } from '@web/core/l10n/translation';
import { PaymentForm } from '@payment/interactions/payment_form';
import { patch } from '@web/core/utils/patch';


patch(PaymentForm.prototype, {

    setup() {
        super.setup();

        this.airwallexDropIn = null;
        this.airwallexLoaded = false;
        this.airwallexEnvironment = null;
    },

    _getPaymentFlow(radio) {
        const providerCode = this._getProviderCode(radio);

        // Airwallex Drop-in owns the complete client-side payment flow,
        // including payment methods that internally redirect (e.g. bank_transfer).
        // From Odoo's perspective, the payment must therefore always use the
        // direct flow and must not enter Odoo's generic redirect handling.
        if (providerCode === 'airwallex') {
            return 'direct';
        }

        return super._getPaymentFlow(...arguments);
    },

    async _processDirectFlow(
        providerCode,
        paymentOptionId,
        paymentMethodCode,
        processingValues
    ) {
        if (providerCode !== 'airwallex') {
            return super._processDirectFlow(...arguments);
        }

        try {
            // =================================================================
            // 1. Airwallex environment
            // =================================================================

            const env =
                processingValues['airwallex_environment']
                || 'demo';


            // =================================================================
            // 2. Initialize Airwallex SDK
            // =================================================================

            if (!this.airwallexLoaded) {

                await loadJS(
                    'https://static.airwallex.com/components/sdk/v1/index.js'
                );

                if (!window.AirwallexComponentsSDK) {
                    throw new Error(
                        _t("Airwallex SDK 載入失敗")
                    );
                }

                await window.AirwallexComponentsSDK.init({
                    env: env,
                    enabledElements: ['payments'],
                });

                this.airwallexLoaded = true;
                this.airwallexEnvironment = env;

            } else if (
                this.airwallexEnvironment !== env
            ) {

                throw new Error(
                    _t(
                        "Airwallex 支付環境與目前交易不一致，請重新載入頁面"
                    )
                );
            }


            // =================================================================
            // 3. Find Drop-in container
            // =================================================================

            const container =
                this.el?.querySelector('#dropIn')
                || document.getElementById('dropIn');

            if (!container) {
                throw new Error(
                    _t("找不到支付容器 #dropIn")
                );
            }


            // =================================================================
            // 4. Destroy previous Drop-in
            // =================================================================

            if (this.airwallexDropIn) {
                this.airwallexDropIn.destroy();
                this.airwallexDropIn = null;
            }


            // =================================================================
            // 5. Payment configuration
            // =================================================================

            const currency =
                processingValues['currency'];

            // Airwallex Drop-in country_code is the shopper country.
            // It must not default to HK, because Aritrz's merchant country
            // is separate from the shopper's country.
            const countryCode =
                processingValues['country_code'];

            // Apple Pay countryCode is the merchant country, not the shopper
            // country. Aritrz is a Hong Kong merchant.
            const merchantCountryCode = 'HK';

            const methodMapping = {
                'HKD': [
                    'wechatpay',
                    'payme',
                ],

                'CNY': [
                    'wechatpay',
                ],

                'SGD': [
                    'pay_now',
                    'wechatpay',
                ],

                'KRW': [
                    'kakaopay',
                    'wechatpay',
                ],
            };


            const options = {
                intent_id:
                    processingValues['intent_id'],

                client_secret:
                    processingValues['client_secret'],

                currency:
                    currency,

                country_code:
                    countryCode,

                applePayRequestOptions: {
                    countryCode:
                        merchantCountryCode,

                    buttonType:
                        'buy',

                    buttonColor:
                        'black',
                },
            };


            if (methodMapping[currency]) {
                options.methods =
                    methodMapping[currency];
            }


            // =================================================================
            // 6. Create Drop-in
            // =================================================================

            this.airwallexDropIn =
                await window.AirwallexComponentsSDK.createElement(
                    'dropIn',
                    options,
                );

            this.airwallexDropIn.mount('dropIn');


            // =================================================================
            // 7. Event handling
            // =================================================================

            this.airwallexDropIn.on(
                'ready',
                () => {
                    // Production 不需要輸出 debug log。
                }
            );


            this.airwallexDropIn.on(
                'success',
                () => {
                    window.location =
                        '/payment/status';
                }
            );


            this.airwallexDropIn.on(
                'error',
                (event) => {

                    const message =
                        event?.error?.message
                        || _t("交易發生錯誤");

                    console.error(
                        'Airwallex payment error:',
                        message
                    );

                    this._displayErrorDialog(
                        _t("支付失敗"),
                        message,
                    );

                    this._enableButton();
                }
            );

        } catch (err) {

            console.error(
                'Airwallex initialization error:',
                err?.message || err
            );

            this._displayErrorDialog(
                _t("初始化錯誤"),
                err?.message
                || _t("支付服務初始化失敗"),
            );

            this._enableButton();
        }
    },
});
