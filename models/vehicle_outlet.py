from openerp import api, fields, models


class VehicleOutlet(models.AbstractModel):
    _name = 'vehicle.outlet'

    contract_id = fields.Many2one('sale.order')
    contract_type = fields.Selection(readonly=True, related="contract_id.contract_type")
    partner_id = fields.Many2one('res.partner', readonly=True, related="contract_id.partner_id")
    street = fields.Char(readonly=True, related='partner_id.street')
    contract_state = fields.Selection(readonly=True, related="contract_id.state")
    active = fields.Boolean(default=True, string="Activo")

    hired = fields.Float(compute="_compute_hired", readonly=True, store=False)
    delivered = fields.Float(compute="_compute_delivered", readonly=True, store=False)
    pending = fields.Float(compute="_compute_pending", readonly=True, store=False)

    product_id = fields.Many2one('product.product', compute="_compute_product_id", readonly=True, store=False)
    location_id = fields.Many2one('stock.location')

    exceeded = fields.Boolean(readonly=True)

    @api.one
    @api.depends('contract_id')
    def _compute_hired(self):
        self.hired = sum(line.product_uom_qty for line in self.contract_id.order_line)

    @api.one
    @api.depends('contract_id')
    def _compute_delivered(self):
        self.delivered = 0

    @api.one
    @api.depends('contract_id')
    def _compute_pending(self):
        self.pending = self.hired - self.delivered

    @api.one
    @api.depends('contract_id')
    def _compute_product_id(self):
        product_id = False
        for line in self.contract_id.order_line:
            product_id = line.product_id
            break
        self.product_id = product_id

    @api.multi
    def fun_transfer(self):
        self.stock_picking_id = self.env['stock.picking'].search([('origin', '=', self.contract_id.name), ('state', 'in', ['confirmed', 'partially_available'])], order='date', limit=1)
        if self.stock_picking_id:
            self.stock_picking_id.force_assign()
        else:
            self.stock_picking_id = self.env['stock.picking'].search([('origin', '=', self.contract_id.name), ('state', '=', 'assigned')], order='date', limit=1)
        if self.stock_picking_id:
            for move in self.stock_picking_id.move_lines:
                move.location_id = self.location_id
            if self.raw_kilos > self.stock_picking_id.move_lines[0].product_uom_qty:
                self.exceeded = True
            self._do_enter_transfer_details()

    @api.multi
    def fun_ship(self):
        stock_picking_id_cancel = self.env['stock.picking'].search([('origin', '=', self.contract_id.name), ('state', '=', 'assigned')], order='date', limit=1)
        if stock_picking_id_cancel:
            stock_picking_id_cancel.action_cancel()

    @api.multi
    def _do_enter_transfer_details(self):
        picking_id = [self.stock_picking_id.id]
        created_id = self.env['stock.transfer_details'].create({'picking_id': len(picking_id) and picking_id[0] or False})
        items = []
        if not self.stock_picking_id.pack_operation_ids:
            self.stock_picking_id.do_prepare_partial()
        for op in self.stock_picking_id.pack_operation_ids:
            if op.product_id:
                item = {
                    'packop_id': op.id,
                    'product_id': op.product_id.id,
                    'product_uom_id': op.product_uom_id.id,
                    'quantity': self.raw_kilos/1000,
                    'package_id': op.package_id.id,
                    'lot_id': op.lot_id.id,
                    'sourceloc_id': op.location_id.id,
                    'destinationloc_id': op.location_dest_id.id,
                    'result_package_id': op.result_package_id.id,
                    'date': op.date,
                    'owner_id': op.owner_id.id,
                }
                items.append(item)
                break
        created_id.item_ids = items
        created_id.do_detailed_transfer()
