# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Payment Provider: Airwallex',
    'version': '1.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Airwallex Card Element Integration for Odoo 19",
    'description': " ",
    'depends': ['payment', 'website_payment', 'website'],
    'data': [
        'views/payment_airwallex_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_airwallex/static/src/interactions/payment_form.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
