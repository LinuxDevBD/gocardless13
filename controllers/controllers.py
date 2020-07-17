# -*- coding: utf-8 -*-
from odoo import http, models
from odoo.http import Response

import logging
import werkzeug
import json
import hmac
import hashlib
import datetime

_logger = logging.getLogger(__name__)

try:
    from .. import gocardless_pro
except ImportError as err:
    _logger.debug(err)    
#endtry

from werkzeug import urls

class Gocardless(http.Controller):

    @http.route('/gocardless/oauth-begin', auth='user')
    def gc_oauth(self, **kw):

        url_base        = http.request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        
        jot_url_base    = 'https://gc-api.jotnarsystems.com'     
        
        environment = http.request.env['ir.config_parameter'].sudo().get_param('gocardless.gc_environment')
       
        prefill = {}

        company = http.request.env.user.company_id        
        prefill = {
            'cust_org_name':    company.display_name,
            'cust_email':       company.email,
            'cust_url':         url_base,
        }

        redir_url = urls.url_join(jot_url_base, "/gc/auth")        
        qs = urls.url_encode(prefill)

        return werkzeug.utils.redirect("{}?{}&{}={}".format(redir_url, qs, environment, environment))

    @http.route('/gocardless/auth-return', auth='user')
    def gc_oauth_return(self, **kw):
        ICPSudo = http.request.env['ir.config_parameter'].sudo()
        
        if kw.get('token'):
            ICPSudo.set_param('gocardless.gc_access_token', kw.get('token'))
            client = gocardless_pro.Client(
                access_token = kw.get('token'),
                environment = ICPSudo.get_param('gocardless.gc_environment')
            )
            creditor = client.creditors.list().records[0]
            if creditor.verification_status == 'action_required':
                return werkzeug.utils.redirect("https://verify{}.gocardless.com".format(
                    ('-sandbox' if ICPSudo.get_param('gocardless.gc_environment') == 'sandbox' else '')
                ))
        
        return werkzeug.utils.redirect("/")

    @http.route('/gocardless/return/', auth='public')
    def gc_return(self, **kw):
        client = gocardless_pro.Client(
            access_token = http.request.env['ir.config_parameter'].sudo().get_param('gocardless.gc_access_token'),
            environment = http.request.env['ir.config_parameter'].sudo().get_param('gocardless.gc_environment')
        )
        for partner in http.request.env['res.partner'].sudo().search([('gc_redirect_flow_id','=',kw.get('redirect_flow_id'))]):
            redirect_flow = client.redirect_flows.complete(
                kw.get('redirect_flow_id'),
                params={
                    "session_token": partner.gc_access_token
                }
            )
            m = http.request.env['gocardless.mandate'].sudo().create({
                'gc_mandate_id': redirect_flow.links.mandate,
                'gc_state': 'pending',
                'partner_id': partner.id,
                'gc_last_state_change': datetime.date.today()
            })
            partner.write({
                'gc_state': 'complete',
                'mandate_id': m.id
            })
            partner.message_post(body="GoCardless: Setup complete, mandate ID: {}".format(redirect_flow.links.mandate))            
        #endfor

        return werkzeug.utils.redirect(redirect_flow.confirmation_url)
    #end gc_return

    @http.route('/gocardless/activate/', auth='public')
    def gc_activate(self, **kw):

        ICPSudo = http.request.env['ir.config_parameter'].sudo()
        gctoken = ICPSudo.get_param('gocardless.gc_access_token')
        gcenv = ICPSudo.get_param('gocardless.gc_environment')
        gcdesc = ICPSudo.get_param('gocardless.gc_description')
        client = gocardless_pro.Client(
            access_token = gctoken,
            environment = gcenv
        )
        gc_url = ICPSudo.get_param('gocardless.gc_custom_domain')
        
        base_url = ICPSudo.get_param('web.base.url') # default: use Odoo base URL
        
        # check sanity of our custom domain setting - if it passes, use that.
        # because we've already set the Odoo base URL it'll fall back if one of these fails
        if type(gc_url) is str:
            if urls.url_parse(url=gc_url).scheme in ['http', 'https']:
                base_url = gc_url
            #endif
        #endif

        for partner in http.request.env['res.partner'].sudo().search([
            ('gc_access_token','=',kw.get('gc_access_token'))
        ]):
            split_name  = str(partner.name).split(" ", 1)
            redirect_flow = client.redirect_flows.create(params={
                'description' : gcdesc if gcdesc else '',
                'session_token' : partner.gc_access_token,
                'success_redirect_url' : urls.url_join(base_url, '/gocardless/return/'),
                'prefilled_customer': {
                    "given_name":           "" if len(split_name) < 1 else split_name[0],
                    "family_name":          "" if len(split_name) < 2 else split_name[1],                    
                    'email' : partner.email,
                    "address_line1": partner.street if partner.street else '',
                    "address_line2": partner.street2 if partner.street2 else '',
                    "city": partner.city if partner.city else '',
                    "postal_code": partner.zip if partner.zip else '',
                    "country_code": partner.country_id.code if partner.country_id.code else ''
                }
            })
            _logger.info("Redirect URL generated: {}".format(redirect_flow.redirect_url))

            partner.write({
                'gc_state': 'pending',
                'gc_last_state_change': datetime.date.today(), 
                'gc_redirect_flow_id': redirect_flow.id
            })

            return werkzeug.utils.redirect(redirect_flow.redirect_url)