# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions
import logging
import datetime
import json

import uuid
import werkzeug

from werkzeug import urls

_logger = logging.getLogger(__name__)

try:
    from .. import gocardless_pro
except ImportError as err:
    _logger.debug(err)    
#endtry

class GC_Importer(models.TransientModel):
    _inherit = 'base_import.import'

    
    def do(self, fields, columns, options, dryrun=False):
        res_import = super(GC_Importer, self).do(fields, columns, options, dryrun)
        # we only want to override for gocardless.mandate models
        if self.res_model == 'gocardless.mandate':
            # it's go time!
            for m in self.env['gocardless.mandate'].sudo().search(['&',('partner_id','=?',False),('partner_email','!=','')]):
                try:
                    p = self.env['res.partner'].sudo().search(['&',('mandate_id','=',False),('email','=',m.partner_email)], limit=1)

                    m.write({
                        'partner_id': p.id,
                        #'gc_last_state_change': datetime.date.today()
                    })
                    p.write({
                        'gc_state': 'complete',
                        'mandate_id': m.id
                    })
                except:
                    continue
            #rof
        #endif
        return res_import
    #end do

#end GC_Importer


class GCPayment(models.Model):
    _name = 'gocardless.payment'
    _description = 'GoCardless Payment'
    
    _rec_name   = 'gc_payment_id'

    amount = fields.Float("Transaction amount")
    
    claim_date  = fields.Datetime("Date claimed")
    post_date   = fields.Datetime("Date posted")
    payout_date = fields.Datetime("Date paid out")

    gc_payment_state = fields.Selection([
        ['pending','Pending'],
        ['created','Created'],
        ['customer_approval_granted','Customer approval: Granted'],
        ['customer_approval_rejected','Customer approval: Rejected'],
        ['submitted','Submitted'],
        ['confirmed','Confirmed'],
        ['cancelled','Cancelled'],
        ['failed','Failed'],
        ['charged_back','Charged back'],
        ['chargeback_cancelled','Chargeback cancelled'],
        ['paid_out','Paid out'],
        ['late_failure_settled','Late failure settled'],
        ['chargeback_settled','Chargeback settled'],
        ['resubmission_requested','Resubmission requested']        
    ], 
        string="Payment State",
        default='created'
    )

    last_state_change = fields.Datetime("Last state change on")

    gc_payment_id = fields.Char("Transaction ID")
    
    invoice_id = fields.Many2one('account.move')

    mandate_id  = fields.Many2one(comodel_name='gocardless.mandate',string='Mandate')

    event_ids   = fields.One2many(comodel_name='gocardless.event', inverse_name='payment_id', string="Events")

    
    def updatePaymentsBatchRun(self):
        # Method no longer used - keeping its stub to avoid
        # unnecessary cron exceptions
        _logger.warning("Deprecated cron job: remove 'Gocardless: Payment Update Batch' from scheduled actions")        
        pass

    
    def retry_payment(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        client = gocardless_pro.Client(
            access_token = ICPSudo.get_param('gocardless.gc_access_token'),
            environment = ICPSudo.get_param('gocardless.gc_environment')
        )

        ret = False
        try:
            ret = client.payments.retry(self.gc_payment_id)
        except gocardless_pro.errors.ApiError as inst:
            raise exceptions.UserError(
                "The payment retry could not be completed for the following reason: {}"
                .format(
                    inst.message
                )
            )
            return

        self.write({'gc_payment_state': 'pending'})
        return ret
        


    
    def gc_cancel_payment(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        client = gocardless_pro.Client(
            access_token = ICPSudo.get_param('gocardless.gc_access_token'),
            environment = ICPSudo.get_param('gocardless.gc_environment')
        )

        try:
            client.payments.cancel(self.gc_payment_id)
        except gocardless_pro.errors.ApiError as inst:
            raise exceptions.UserError(
                "The payment could not be cancelled for the following reason: {}"
                .format(
                    inst.message
                )
            )


#end GCPayment

class Invoice(models.Model):
    _inherit = 'account.move'

    # Odoo 13 compatibility thunks
    number = fields.Char(related='name', store=False)

    gc_last_payment_attempt = fields.Datetime("Date of last payment attempt")

    gc_payment_attempted = fields.Boolean("GC Charged")

    # calculate default value for pay_by_gc
    def _gc_get_pay_by_gc(self):
        for rec in self:
            return rec.partner_id.use_gc

    gc_pay_by_gc = fields.Boolean("Take payment for this invoice by GoCardless", default=_gc_get_pay_by_gc)
    
    gc_retry_payment = fields.Boolean("Retry payment?")

    gc_enable_payment_recreate = fields.Boolean("Recreate payment available", default=False)

    gc_payments = fields.One2many(string="Payment Records", comodel_name='gocardless.payment', inverse_name='invoice_id')

    active_payment_id   = fields.Many2one(comodel_name='gocardless.payment', string='Current Payment')

    gc_display_gc = fields.Boolean(store=False, compute='_compute_display_gc')

    @api.depends('partner_id')
    def _compute_display_gc(self):
        if (self.env['ir.config_parameter'].sudo().get_param('gocardless.gc_access_token') not in ['', False, None]):
            for rec in self:
                rec.gc_display_gc = (rec.partner_id.gc_state not in ['setup', 'pending'])
        else:
            for rec in self:
                rec.gc_display_gc = False

    @api.onchange('partner_id')
    def _onchange_partner(self):
        self.gc_pay_by_gc = self.partner_id.use_gc
        

    
    def action_gocardless_retry_payment(self):
        oops = False
        try:
            return self.active_payment_id.retry_payment()
        except exceptions.UserError as inst:
            _logger.info("OOPS")
            oops = inst
            if "inactive mandate" in inst.message:
                _logger.info("Enabling recreate button")
                self.gc_enable_payment_recreate = True
                self.write({
                    'gc_enable_payment_recreate': True
                })
                self.env.cr.commit()
        finally:            
            if oops:
                _logger.info("We got an oops, raising it")
                raise oops
        # self.gc_retry_payment = True
        # return self.action_gocardless_take_payment()

    
    def action_gocardless_recreate_payment(self):
        self.gc_retry_payment = True
        return self.action_gocardless_take_payment()        

    
    def action_gocardless_take_payment(self):
        invoice = self
        
        ICPSudo = self.env['ir.config_parameter'].sudo()
        client = gocardless_pro.Client(
            access_token = ICPSudo.get_param('gocardless.gc_access_token'),
            environment = ICPSudo.get_param('gocardless.gc_environment')
        )

        try:
            payment = client.payments.create(
                params = {
                    "amount" : int((invoice.amount_total * 100)), # format amount in cents
                    "currency" : invoice.currency_id.name,
                    "links" : {
                        "mandate" : invoice.partner_id.gc_mandate_id
                    },
                    "metadata": {
                        "invoice_number": invoice.number
                    }
                },
                headers = {
                    'Idempotency-Key': '{}-{}'.format(invoice.partner_id.gc_mandate_id, invoice.number) if not invoice.gc_retry_payment else 'retry-{}-{}-{}'.format(invoice.partner_id.gc_mandate_id, invoice.number, datetime.datetime.now())
                                                        # this key allows us to set a unique id for the tx in question
                                                        # - making sure we don't accidentally bill a partner twice
                }
            )
        except gocardless_pro.errors.ApiError as inst:
            raise exceptions.Warning(
                "Payment could not be submitted to GoCardless for the following reason: {}"
                .format(
                    inst.message
                )
            )

        invoice.write({
            'gc_last_payment_attempt': datetime.datetime.now(),
            'gc_payment_attempted': True,           # we've attempted to take payment
            'gc_retry_payment': False,              # if we've done a manual retry, cancel this too
            'gc_enable_payment_recreate': False     # we definitely want to cancel this one
            })

        mandate = self.env['gocardless.mandate'].search([('gc_mandate_id','=',invoice.partner_id.gc_mandate_id)], limit=1)

        p = self.env['gocardless.payment'].sudo().create({
            'amount': invoice.amount_total,
            'claim_date': datetime.datetime.now(),
            'mandate_id': mandate.id,
            'gc_payment_state': 'pending',
            'gc_payment_id': payment.id,
            'invoice_id': invoice.id
        })

        invoice.write({
            'active_payment_id': p.id
        })

        invoice.message_post(body="GoCardless payment requested for {} {} with payment ID {}".format(
            invoice.currency_id.name, invoice.amount_total, payment.id
        ))

    
    def takePaymentBatchRun(self):
        _logger.warning("Deprecated cron job: remove 'Gocardless: Invoice Take Payment Batch' from scheduled actions")
        pass

#end Invoice

class GC_Mandate(models.Model):
    _name = 'gocardless.mandate'
    _description = 'GoCardless Mandate'

    _rec_name   = 'gc_mandate_id'

    gc_state    = fields.Selection(
        [
            ['pending','Pending'],
            ['created','Created'],
            ['submitted','Submitted'],
            ['active','Active'],
            ['reinstated','Reinstated'],
            ['cancelled','Cancelled'],
            ['failed','Failed'],
            ['expired','Expired'],
            ['resubmission_requested','Resubmission requested'],
            ['replaced','Replaced'],
            ['customer_approval_granted','Customer approval granted'],
            ['customer_approval_skipped','Customer approval skipped']
        ], 
        string="Mandate state:",
        required=True
    )

    gc_last_state_change = fields.Date("Last updated", 
        default=datetime.date(year=1970,month=1,day=1)
    )

    gc_mandate_id       = fields.Char("GoCardless Mandate ID", required=True)

    event_ids           = fields.One2many(comodel_name='gocardless.event', inverse_name='mandate_id', string="Events")

    partner_id          = fields.Many2one(comodel_name='res.partner', string='Partner')
    partner_email       = fields.Char(string='Email', related='partner_id.email', store=True, readonly=False)

    
    def mandateUpdate(self):
        # Method no longer used - keeping its stub to avoid
        # unnecessary cron exceptions
        _logger.warning("Deprecated cron job: remove 'Gocardless: Mandate Update Batch' from scheduled actions")
        pass

#end GC_Mandate


class GC_Event(models.Model):
    _name = 'gocardless.event'
    _description = 'GoCardless Event'

    _rec_name = 'event_id'

    event_id        = fields.Char(string="GoCardless Event ID")
    action          = fields.Char(string="Action")
    created_at      = fields.Datetime(string="Event Date")

    cause           = fields.Char(string="Reason")
    ev_description  = fields.Char(string="Reason Description")
    
    ev_origin       = fields.Selection(
        selection = [
            ('bank','Bank'),
            ('gocardless','GoCardless'),
            ('api','API'),
            ('customer','Customer')
        ],
        string="Event origin"
    )

    ev_reason_code  = fields.Char(string="Bank Reason Code")
    ev_scheme       = fields.Char(string="Direct Debit Scheme")

    resource_type   = fields.Selection(
        selection = [
            ('payments','Payment'),
            ('mandates','Mandate'),
            ('payouts','Payout'),
            ('refunds','Refunds'),
            ('subscriptions','Subscriptions')
        ],
        string="Resource type"
    )

    payment_id      = fields.Many2one(comodel_name='gocardless.payment',string="Payment")
    mandate_id      = fields.Many2one(comodel_name='gocardless.mandate',string="Mandate")

    
    def do_full_event_refresh(self):
        self.process_events()

    
    def doEvents(self):
        # we're in the batch run, so pick up the last 14 days
        date_cutoff = "{}T{}Z".format(datetime.date.today() - datetime.timedelta(days=14), datetime.datetime.min.time())        
        self.process_events(date_cutoff)

    def process_events(self, date_cutoff=None):
        # Here we go with one huge-ass batch run...
        # It's about here that I started to lose my mind ;-)

        ICPSudo = self.env['ir.config_parameter'].sudo()
        gctoken = ICPSudo.get_param('gocardless.gc_access_token')
        gcenv = ICPSudo.get_param('gocardless.gc_environment')

        client = gocardless_pro.Client(
            access_token = gctoken,
            environment = gcenv
        )

        events = client.events.list(
            params = {
                "created_at[gte]": date_cutoff
            } if date_cutoff else {
                "limit": 500
            }
        ).records
        
        count = 0
        for event in events:
            # Heavy lifting loop. Should probably look at refactoring this into an event dispatcher.
            # Actually yeah, that's a good idea.
            # Edit: we did it.
            
            # anyway, to business.

            existing_event = False

            # first, make sure we don't already have the event ID in the database.
            if len(self.search([('event_id','=',event.id)])._ids) > 0:
                # event already exists (length of search result > 0),
                # so get on with the next one
                existing_event = self.env['gocardless.event'].sudo().search([('event_id','=',event.id)], limit=1)

            # parse the date into a format Python (and thus Odoo) actually likes:
            eventDate = datetime.datetime.strptime(event.created_at, "%Y-%m-%dT%H:%M:%S.%fZ")

            if not existing_event:
            # let's go ahead and create the event
                self.env['gocardless.event'].sudo().create({
                    'event_id':         event.id,
                    'action':           event.action,
                    'created_at':       eventDate,
                    'cause':            event.details.cause,
                    'ev_description':   event.details.description,
                    'ev_origin':        event.details.origin,
                    'ev_reason_code':   event.details.reason_code,
                    'ev_scheme':        event.details.scheme,
                    'resource_type':    event.resource_type,
                    'mandate_id':       self.env['gocardless.mandate'].search([('gc_mandate_id','=',event.links.mandate)], limit=1).id if event.resource_type == 'mandates' else None,
                    'payment_id':       self.env['gocardless.payment'].search([('gc_payment_id','=',event.links.payment)], limit=1).id if event.resource_type == 'payments' else None                
                })
            else:
                # event already exists
                # are we in a reprocess? let's work this out from what we know
                if date_cutoff:
                    # there's a cutoff date specified, so no we're not
                    continue
                else:
                    # we're in a reprocess, update the event
                    existing_event.write({
                        'event_id':         event.id,
                        'action':           event.action,
                        'created_at':       eventDate,
                        'cause':            event.details.cause,
                        'ev_description':   event.details.description,
                        'ev_origin':        event.details.origin,
                        'ev_reason_code':   event.details.reason_code,
                        'ev_scheme':        event.details.scheme,
                        'resource_type':    event.resource_type,
                        'mandate_id':       self.env['gocardless.mandate'].search([('gc_mandate_id','=',event.links.mandate)], limit=1).id if event.resource_type == 'mandates' else None,
                        'payment_id':       self.env['gocardless.payment'].search([('gc_payment_id','=',event.links.payment)], limit=1).id if event.resource_type == 'payments' else None                
                    })



            if event.resource_type == 'payments':
                self.dispatchPaymentEvents(event)
            elif event.resource_type == 'mandates':
                self.dispatchMandateEvents(event)
            #endif

            count += 1

        #rof
        _logger.info('Processed {} events'.format(count))
    #end doEvents

    def dispatchPaymentEvents(self, event):
        ICPSudo = self.env['ir.config_parameter'].sudo()

        post_journals = ICPSudo.get_param('gocardless.gc_keep_journal')
        jid = ICPSudo.get_param('gocardless.gc_journal_id')
        journal = self.env['account.journal'].search([('id','=',jid)])


        gc_payments = self.env['gocardless.payment'].sudo().search([('gc_payment_id','=',event.links.payment)])
        for gc_payment in gc_payments:
            eventDate = datetime.datetime.strptime(event.created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
            if (gc_payment.gc_payment_state != event.action) and (eventDate > (fields.Datetime.from_string(gc_payment.last_state_change) if gc_payment.last_state_change else datetime.datetime(1970,1,1))):     
                # let's check we actually need to update something (disabled for debug)
                vals = {
                    'gc_payment_state': event.action
                }
                if event.action == 'confirmed':
                    vals.update({'post_date': eventDate})
                    
                    if post_journals:
                        payment = self.env['account.payment'].create({
                            'payment_type': 'inbound',
                            'amount': gc_payment.amount,
                            'payment_method_id': self.env['account.payment.method'].search([('payment_type','=','inbound'),('code','=','manual')]).id,
                            'payment_date': datetime.date.today(),
                            'journal_id': int(journal.id),
                            'currency_id': int(gc_payment.invoice_id.currency_id.id),
                            'communication': gc_payment.invoice_id.number,
                            'invoice_ids': [(6,0,[int(gc_payment.invoice_id.id)])],
                            'partner_type': 'customer', #TODO: sort out the hardcoded bit here if needed
                            'partner_id': int(gc_payment.invoice_id.partner_id.id)
                        })
                        payment.post()                        
                    #endif
                #endif

                if event.action == 'paid_out':
                    vals.update({'payout_date': eventDate})

                vals.update({'last_state_change': eventDate})
                gc_payment.write(vals)

                msg = "Payment update: Payment ID {} State: {} Amount: {}".format(gc_payment.gc_payment_id, gc_payment.gc_payment_state, gc_payment.amount)
                gc_payment.invoice_id.message_post(body=msg)

            #endif

        pass

    def dispatchMandateEvents(self, event):
        
        for mandate in self.env['gocardless.mandate'].sudo().search([('gc_mandate_id','=',event.links.mandate)]):
            eventDate = datetime.datetime.strptime(event.created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
            if event.action == 'mandate_replaced':
                mandate.write({
                    'gc_mandate_id': event.links.new_mandate,
                    'gc_last_state_change': eventDate
                })                
                return

            if (mandate.gc_state != event.action) and (eventDate > fields.Datetime.from_string(mandate.gc_last_state_change)):     
                # let's check we actually need to update something (disabled for debug)
                mandate.write({
                    'gc_state': event.action,
                    'gc_last_state_change': eventDate
                })
                msg = "GoCardless: Mandate ID {} changed state to {}".format(mandate.gc_mandate_id,mandate.gc_state)
                mandate.partner_id.message_post(body=msg)
            #endif
        #rof

                        


class GC_Partner(models.Model):
    _inherit = 'res.partner'

    # use_gc      = fields.Boolean("Use GoCardless to collect payments?", default=False)
    use_gc      = fields.Boolean(compute='_compute_use_gc', store=False)

    @api.depends('gc_state')
    def _compute_use_gc(self):
        for rec in self:
            rec.use_gc = (rec.gc_state in ['pending', 'complete'])

    gc_state    = fields.Selection(
        [
            ['setup','Awaiting Setup'],
            ['pending','Pending'],
            ['complete','Setup Complete']
        ], 
        string="GoCardless setup state:",        
        default='setup'
    )

    gc_mandate_state    = fields.Selection(related='mandate_id.gc_state')

    gc_last_state_change = fields.Date("Last updated", default=datetime.date(year=1970,month=1,day=1))

    gc_mandate_id       = fields.Char("GoCardless Mandate ID", related='mandate_id.gc_mandate_id', store=False)
    gc_redirect_flow_id = fields.Char()
    gc_redirect_url     = fields.Char()

    gc_access_token     = fields.Char()

    mandate_id          = fields.Many2one(
        comodel_name='gocardless.mandate',
        string="GoCardless Mandate")


    
    def action_send_partner_email(self):
        self.send_partner_email(self)
        # self.write({
        #     'use_gc':    True
        # })

    def send_partner_email(self, partner, batch_run = False):
        ICPSudo = self.env['ir.config_parameter'].sudo()

        proceed = (ICPSudo.get_param('gocardless.gc_access_token') not in ['', False, None])

        if not proceed:
            raise exceptions.UserError(
                "Connect to your GoCardless account first!"
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

        _logger.info("Got something to do: {}".format(partner.name))
        count = partner.invoice_ids.search_count([('partner_id','=',partner.id),('state','!=','draft')])
        if count <= 0 and batch_run:
            return
        #endif

        gc_token = str(uuid.uuid4())
        redirect_url = urls.url_join(base_url, '/gocardless/activate/?gc_access_token={}'.format(gc_token))
        partner.write({
            'gc_state': 'pending',
            'gc_last_state_change': datetime.date.today(), 
            'gc_redirect_url': redirect_url,
            'gc_access_token': gc_token
        })
        
        # issue the email invite
        mail_template = self.env.ref('gocardless.gc_mandate_invite_email')
        self.env['mail.template'].browse(mail_template.id).send_mail(partner.id)

    
    
    def addPartnerBatchRun(self):

        date_last_week = datetime.date.today() - datetime.timedelta(days=7)
        for partner in self.search([('gc_state', 'in', ['pending', 'complete']),
                '|',
                ('gc_state','=','setup'),
                '&',
                ('gc_state','=','pending'),
                ('gc_last_state_change','<',date_last_week), # resubmit stale requests
            ]):
            self.send_partner_email(partner, batch_run=True)

        #endfor
    #end addPartnerBatchRun

#end Partner



class ResConfigSettings(models.TransientModel):
    
    _inherit = 'res.config.settings'

    gc_access_token     = fields.Char("Access Token")  

    gc_environment      = fields.Selection([['sandbox','Sandbox'],['live','Live']], "API environment", default='sandbox')
    gc_description      = fields.Char("Description (to be shown on the GoCardless mandate page)")
    gc_webhook_secret   = fields.Char("Secret (Optional, for verification of GoCardless callbacks)")
    gc_webhook_url      = fields.Char("Webhook return URL")

    gc_custom_domain    = fields.Char("Custom URL prefix (leave blank to use the default Odoo URL)")

    gc_keep_journal     = fields.Boolean("Record GoCardless payments in an accounting journal?", default=True)

    
    def gocardless_connect(self):
        self.set_values()
        return {
            'type': 'ir.actions.act_url',
            'url': '/gocardless/oauth-begin',
            'target': 'self',
        }

    
    def do_full_event_refresh(self):
        return self.env['gocardless.event'].do_full_event_refresh()

    
    def get_default_journal(self):
        return self.env.ref('gocardless.journal_gocardless').id

    
    def get_journals_selection(self):
        ret = []
        for j in self.env['account.journal']:
            ret.append([j.id, j.name])
        return ret

    gc_journal_id       = fields.Many2one(comodel_name='account.journal',string="Journal to record payments in",default=get_default_journal)
    
    _defaults = {
        'gc_keep_journal': True,
        'gc_journal_id': get_default_journal        
    }

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()

        jid = int(ICPSudo.get_param('gocardless.gc_journal_id'))
        if not jid:
            jid = self.env.ref('gocardless.journal_gocardless').id

        kj = ICPSudo.get_param('gocardless.gc_keep_journal')
        if kj is None:
            kj = True

        res.update(       
            gc_access_token = ICPSudo.get_param('gocardless.gc_access_token'),
            gc_environment = ICPSudo.get_param('gocardless.gc_environment'),
            gc_description = ICPSudo.get_param('gocardless.gc_description'),
            gc_webhook_secret = ICPSudo.get_param('gocardless.gc_webhook_secret'),
            gc_webhook_url = urls.url_join(ICPSudo.get_param('web.base.url'),'/gocardless/webhook/'),
            gc_custom_domain = ICPSudo.get_param('gocardless.gc_custom_domain'),
            gc_keep_journal = kj,
            gc_journal_id = jid
        )
        return res
    #end get_values

    
    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()
        ICPSudo.set_param('gocardless.gc_access_token', self.gc_access_token)
        ICPSudo.set_param('gocardless.gc_environment', self.gc_environment)
        ICPSudo.set_param('gocardless.gc_description', self.gc_description)
        ICPSudo.set_param('gocardless.gc_webhook_secret', self.gc_webhook_secret)
        ICPSudo.set_param('gocardless.gc_custom_domain', self.gc_custom_domain)
        ICPSudo.set_param('gocardless.gc_keep_journal', self.gc_keep_journal)
        ICPSudo.set_param('gocardless.gc_journal_id', int(self.gc_journal_id.id))
    #end set_values


#end ResConfigSettings