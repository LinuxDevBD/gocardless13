# -*- coding: utf-8 -*-
{
    'name': "GoCardless Direct Debit Payment Processing",

    'summary': """
        Enables Odoo to take payments using Direct Debit schemes such as Bacs, SEPA, ACH, BECS, and more via GoCardless.""",

#    'description': """
#        Enables Odoo invoices to handle Direct Debit schemes such as Bacs, SEPA, ACH, BECS, and more via GoCardless.
#        This application transmits the following data to GoCardless Ltd for the purpose of setting up a Direct Debit mandate and taking payments: 
#        Customer email address, invoice number, invoice amount
#        No customer information is shared with Jötnar Systems at any time.
#    """,

    'author': "Jötnar Systems",
    'website': "https://www.jotnarsystems.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'Accounting',
    'version': '2.0',
    'images': ['static/description/gc-jot.png'],

    # Commercial information
    'license': 'OPL-1',
    'price': 0,
    'currency': 'EUR',
    'support': 'support@jotnarsystems.com',

    # any module necessary for this one to work correctly
    'depends': ['base', 'account'],
    
    # Python packages required for this module
    # 'external_dependencies': {'python': ['gocardless_pro']},


    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/ui.xml',
        'views/templates.xml',
        'data/gocardless_data.xml',
        'wizard/wizard.xml'
        
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
    'application': True,
}