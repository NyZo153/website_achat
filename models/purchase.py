# -*- coding: utf-8 -*-

import random
#from openerp.osv import osv, fields
from openerp import SUPERUSER_ID
from openerp.osv import osv, orm, fields
from openerp.addons.web.http import request

class purchase_order(osv.osv):
    _inherit= 'purchase.order'

    def _cart_qty(self, cr, uid, ids, field_name, arg, context=None):
        res = dict()
        for order in self.browse(cr, uid, ids, context=context):
            res[order.id] = int(sum(l.product_uom_qty for l in (order.website_order_line or [])))
        return res

    _columns = {
        'website_order_line': fields.one2many(
            'purchase.order.line', 'order_id',
            string='Order Lines displayed on Website', readonly=True,
            help='Order Lines to be displayed on the website. They should not be used for computation purpose.',
        ),
        'cart_quantity': fields.function(_cart_qty, type='integer', string='Cart Quantity'),
        'payment_acquirer_id': fields.many2one('payment.acquirer', 'Payment Acquirer', on_delete='set null'),
        'payment_tx_id': fields.many2one('payment.transaction', 'Transaction', on_delete='set null'),
    }

    _defaults = {
        'location_id': 12,
        }

    def _get_errors(self, cr, uid, order, context=None):
        return []

    def _get_website_data(self, cr, uid, order, context):
        return {
            'partner': order.partner_id.id,
            'order': order
        }

    def _cart_find_product_line(self, cr, uid, ids, product_id=None, line_id=None, context=None, **kwargs):
        for so in self.browse(cr, uid, ids, context=context):
            domain = [('order_id', '=', so.id), ('product_id', '=', product_id)]
            if line_id:
                domain += [('id', '=', line_id)]
            return self.pool.get('purchase.order.line').search(cr, SUPERUSER_ID, domain, context=context)

    def _website_product_id_change(self, cr, uid, ids, order_id, product_id, qty=0, line_id=None, context=None):
        so = self.pool.get('purchase.order').browse(cr, uid, order_id, context=context)
        print (product_id)

        values = self.pool.get('purchase.order.line').product_id_change(cr, SUPERUSER_ID, [],
             pricelist_id=so.pricelist_id.id,
#             product=product_id,
            product_id=product_id,
            partner_id=so.partner_id.id,
            fiscal_position_id=so.fiscal_position.id,
            uom_id=None,
            qty=qty,
            context=context
        )['value']

        print (values)

        if line_id:
            line = self.pool.get('purchase.order.line').browse(cr, SUPERUSER_ID, line_id, context=context)
            values['name'] = line.name
        else:
            product = self.pool.get('product.product').browse(cr, uid, product_id, context=context)
            values['name'] = product.description_sale or product.name

        values['product_id'] = product_id
        values['order_id'] = order_id
        if values.get('tax_id') != None:
            values['tax_id'] = [(6, 0, values['tax_id'])]
        return values

    def _cart_update(self, cr, uid, ids, product_id=None, line_id=None, add_qty=0, set_qty=0, context=None, **kwargs):
        """ Add or set product quantity, add_qty can be negative """
        sol = self.pool.get('purchase.order.line')

        quantity = 0
        for so in self.browse(cr, uid, ids, context=context):
            if line_id != False:
                line_ids = so._cart_find_product_line(product_id, line_id, context=context, **kwargs)
                if line_ids:
                    line_id = line_ids[0]

            # Create line if no line with product_id can be located
            if not line_id:
                values = self._website_product_id_change(cr, uid, ids, so.id, product_id, qty=1, context=context)
                line_id = sol.create(cr, SUPERUSER_ID, values, context=context)
                if add_qty:
                    add_qty -= 1

            # compute new quantity
            if set_qty:
                quantity = set_qty
            elif add_qty != None:
                quantity = sol.browse(cr, SUPERUSER_ID, line_id, context=context).product_qty + (add_qty or 0)

            # Remove zero of negative lines
            if quantity <= 0:
                sol.unlink(cr, SUPERUSER_ID, [line_id], context=context)
            else:
                # update line
                values = self._website_product_id_change(cr, uid, ids, so.id, product_id, qty=quantity, line_id=line_id, context=context)
                values['product_uom_qty'] = quantity
                sol.write(cr, SUPERUSER_ID, [line_id], values, context=context)

        return {'line_id': line_id, 'quantity': quantity}

    def _cart_accessories(self, cr, uid, ids, context=None):
        for order in self.browse(cr, uid, ids, context=context):
            s = set(j.id for l in (order.website_order_line or []) for j in (l.product_id.accessory_product_ids or []))
            s -= set(l.product_id.id for l in order.order_line)
            product_ids = random.sample(s, min(len(s),3))
            return self.pool['product.product'].browse(cr, uid, product_ids, context=context)

class website(orm.Model):
    _inherit = 'website'

    def sale_product_domain(self, cr, uid, ids, context=None):
        return [("purchase_ok", "=", True)]

    def purchase_get_order(self, cr, uid, ids, force_create=False, code=None, update_pricelist=None, context=None):
        purchase_order_obj = self.pool['purchase.order']
        purchase_order_id = request.session.get('purchase_order_id')
        purchase_order = None
        # create so if needed
        if not purchase_order_id and (force_create or code):
            # TODO cache partner_id session
            partner = self.pool['res.users'].browse(cr, SUPERUSER_ID, uid, context=context).partner_id

            for w in self.browse(cr, uid, ids):
                values = {
                    'user_id': w.user_id.id,
                    'partner_id': partner.id,
                    'pricelist_id': partner.property_product_pricelist.id,
#                     'section_id': self.pool.get('ir.model.data').get_object_reference(cr, uid, 'website', 'salesteam_website_sales')[1],
                }

                purchase_order_id = purchase_order_obj.create(cr, SUPERUSER_ID, values, context=context)
#                 print (purchase_order_id)

                values = purchase_order_obj.onchange_partner_id(cr, SUPERUSER_ID, [], partner.id, context=context)['value']
                purchase_order_obj.write(cr, SUPERUSER_ID, [purchase_order_id], values, context=context)
                request.session['purchase_order_id'] = purchase_order_id
        if purchase_order_id:
            # TODO cache partner_id session
            partner = self.pool['res.users'].browse(cr, SUPERUSER_ID, uid, context=context).partner_id

            purchase_order = purchase_order_obj.browse(cr, SUPERUSER_ID, purchase_order_id, context=context)
            if not purchase_order.exists():
                request.session['purchase_order_id'] = None
                return None

            # check for change of pricelist with a coupon
            if code and code != purchase_order.pricelist_id.code:
                pricelist_ids = self.pool['product.pricelist'].search(cr, SUPERUSER_ID, [('code', '=', code)], context=context)
                if pricelist_ids:
                    pricelist_id = pricelist_ids[0]
                    request.session['purchase_order_code_pricelist_id'] = pricelist_id
                    update_pricelist = True
                request.session['purchase_order_code_pricelist_id'] = False

            pricelist_id = request.session.get('purchase_order_code_pricelist_id') or partner.property_product_pricelist.id

            # check for change of partner_id ie after signup
            if purchase_order.partner_id.id != partner.id and request.website.partner_id.id != partner.id:
                flag_pricelist = False
                if pricelist_id != purchase_order.pricelist_id.id:
                    flag_pricelist = True
                fiscal_position = purchase_order.fiscal_position and purchase_order.fiscal_position.id or False

                values = purchase_order_obj.onchange_partner_id(cr, SUPERUSER_ID, [purchase_order_id], partner.id, context=context)['value']
                if values.get('fiscal_position'):
                    order_lines = map(int,purchase_order.order_line)
                    values.update(purchase_order_obj.onchange_fiscal_position(cr, SUPERUSER_ID, [],
                        values['fiscal_position'], [[6, 0, order_lines]], context=context)['value'])

                values['partner_id'] = partner.id
                purchase_order_obj.write(cr, SUPERUSER_ID, [purchase_order_id], values, context=context)

                if flag_pricelist or values.get('fiscal_position') != fiscal_position:
                    update_pricelist = True

            # update the pricelist
            if update_pricelist:
                values = {'pricelist_id': pricelist_id}
                values.update(purchase_order.onchange_pricelist_id(pricelist_id, None)['value'])
                purchase_order.write(values)
                for line in purchase_order.order_line:
                    purchase_order._cart_update(product_id=line.product_id.id, line_id=line.id, add_qty=0)

            # update browse record
            if (code and code != purchase_order.pricelist_id.code) or purchase_order.partner_id.id !=  partner.id:
                purchase_order = purchase_order_obj.browse(cr, SUPERUSER_ID, purchase_order.id, context=context)

            print (purchase_order)

        return purchase_order

    def purchase_get_transaction(self, cr, uid, ids, context=None):
        transaction_obj = self.pool.get('payment.transaction')
        tx_id = request.session.get('purchase_transaction_id')
        if tx_id:
            tx_ids = transaction_obj.search(cr, SUPERUSER_ID, [('id', '=', tx_id), ('state', 'not in', ['cancel'])], context=context)
            if tx_ids:
                return transaction_obj.browse(cr, SUPERUSER_ID, tx_ids[0], context=context)
            else:
                request.session['purchase_transaction_id'] = False
        return False

    def purchase_reset(self, cr, uid, ids, context=None):
        request.session.update({
            'purchase_order_id': False,
            'purchase_transaction_id': False,
            'purchase_order_code_pricelist_id': False,
        })