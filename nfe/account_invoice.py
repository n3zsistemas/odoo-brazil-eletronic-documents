# -*- encoding: utf-8 -*-
###############################################################################
#                                                                             #
# Copyright (C) 2013  Danimar Ribeiro 26/06/2013                              #
#                                                                             #
#This program is free software: you can redistribute it and/or modify         #
#it under the terms of the GNU Affero General Public License as published by  #
#the Free Software Foundation, either version 3 of the License, or            #
#(at your option) any later version.                                          #
#                                                                             #
#This program is distributed in the hope that it will be useful,              #
#but WITHOUT ANY WARRANTY; without even the implied warranty of               #
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the                #
#GNU Affero General Public License for more details.                          #
#                                                                             #
#You should have received a copy of the GNU Affero General Public License     #
#along with this program.  If not, see <http://www.gnu.org/licenses/>.        #
###############################################################################

import os
import datetime
from openerp.osv import orm
from openerp.tools.translate import _
from .sped.nfe.document import NFe200
from .sped.nfe.validator.xml import validation
from .sped.nfe.validator.config_check import validate_nfe_configuration
from .sped.nfe.processing.xml import monta_caminho_nfe
from .sped.nfe.processing.xml import send


class AccountInvoice(orm.Model):
    """account_invoice overwritten methods"""
    _inherit = 'account.invoice'

    def nfe_export(self, cr, uid, ids, context=None):

        for inv in self.browse(cr, uid, ids):

            company_pool = self.pool.get('res.company')
            company = company_pool.browse(cr, uid, inv.company_id.id)

            validate_nfe_configuration(company)

            nfe_obj = NFe200()
            nfes = nfe_obj.get_xml(cr, uid, ids, int(company.nfe_environment))
            for nfe in nfes:
                erro = validation(nfe['nfe'])
                nfe_key = nfe['key'][3:]
                if erro:
                    raise orm.except_orm(
                         _(u'Erro na validação da NFe!'), erro)

                self.write(cr, uid, inv.id, {'nfe_access_key': nfe_key})
                save_dir = os.path.join(company.nfe_export_folder, monta_caminho_nfe(int(company.nfe_environment), chave_nfe=nfe_key) + 'tmp/')
                nfe_file = nfe['nfe'].encode('utf8')

                file_path = save_dir + nfe_key + '-nfe.xml'
                try:
                    if not os.path.exists(save_dir):
                        os.makedirs(save_dir)
                    f = open(file_path, 'w')
                except IOError:
                    raise orm.except_orm(
                        _(u'Erro!'),
                        _(u"""Não foi possível salvar o arquivo em disco,
                            verifique as permissões de escrita e o caminho
                            da pasta"""))
                else:
                    f.write(nfe_file)
                    f.close()


                    event_obj = self.pool.get('l10n_br_account.document_event')
                    nfe_send_id = event_obj.create(cr, uid, {
                        'type': '0',
                        'company_id': company.id,
                        'origin': '[NF-E]' + inv.internal_number,
                        'file_sent': file_path,
                        'create_date': datetime.datetime.now(),
                        'state': 'draft',
                        'document_event_ids': inv.id
                        }, context)
                    self.write(cr, uid, ids, {'state':'sefaz_export'}, context=context)

    def action_invoice_send_nfe(self, cr, uid, ids, context=None):

        for inv in self.browse(cr, uid, ids):
            company_pool = self.pool.get('res.company')
            company = company_pool.browse(cr, uid, inv.company_id.id)

            event_obj = self.pool.get('l10n_br_account.document_event')

            event  = max(event_obj.search(cr, uid, [('document_event_ids','=',inv.id),('type','=','0')], context=context))

            send_event  = event_obj.browse(cr, uid, [event])[0]

            arquivo = send_event.file_sent

            nfe_obj = NFe200()
            nfe = []
            results = []
            protNFe = {}
            protNFe["state"] = 'sefaz_exception'
            protNFe["status_code"] = ''
            protNFe["message"] = ''

            try:
                nfe.append(nfe_obj.set_xml(arquivo))

                for processo in send(company, nfe):

                    vals = {
                            'type': str(processo.webservice),
                            'status': processo.resposta.cStat.valor,
                            'response': '',
                            'company_id': company.id,
                            'origin': '[NF-E]' + inv.internal_number,
                            'file_sent': processo.arquivos[0]['arquivo'],
                            'file_returned': processo.arquivos[1]['arquivo'],
                            'message': processo.resposta.xMotivo.valor,
                            'state': 'done',
                            'document_event_ids': inv.id}
                    results.append(vals)

                    if processo.webservice == 1:
                        for prot in processo.resposta.protNFe:
                            protNFe["status_code"] = prot.infProt.cStat.valor
                            protNFe["message"] = prot.infProt.xMotivo.valor
                            vals["status"] = prot.infProt.cStat.valor
                            vals["message"] = prot.infProt.xMotivo.valor
                            if prot.infProt.cStat.valor in ('100', '150', '110', '301', '302'):
                                protNFe["state"] = 'open'
            except Exception as e:
                vals = {
                        'type': '-1',
                        'status': '000',
                        'response': 'response',
                        'company_id': company.id,
                        'origin': '[NF-E]' + inv.internal_number,
                        'file_sent': 'False',
                        'file_returned': 'False',
                        'message': 'Erro desconhecido ' + e.message,
                        'state': 'done',
                        'document_event_ids': inv.id
                        }
                results.append(vals)
            finally:
                for result in results:
                    if result['type'] == '0':
                        event_obj.write(
                            cr, uid, inv.account_document_event_ids[0].id,
                            result, context)
                    else:
                        event_obj.create(cr, uid, result, context)

                self.write(cr, uid, inv.id, {
                     'nfe_status': protNFe["status_code"] + ' - ' + protNFe["message"],
                     'nfe_date': datetime.datetime.now(),
                     'state': protNFe["state"]
                     }, context)
        return True
    
    def action_cancel(self, cr, uid, ids, context=None):
        raise orm.except_orm(_('Error !'), u'Por enquanto não vai cancelar')
        self.cancel_invoice_online(cr, uid, ids, context)
        
        return super(AccountInvoice,self).action_cancel(cr, uid, ids, context)
    
    
    def cancel_invoice_online(self, cr, uid, ids,context=None):
        record = self.browse(cr, uid, ids[0])
        if record.document_serie_id:
            if record.document_serie_id.fiscal_document_id:
                if not record.document_serie_id.fiscal_document_id.electronic:
                    return
                
        if record.state in ('open','paid'):
            company_pool = self.pool.get('res.company')
            company = company_pool.browse(cr, uid, record.company_id.id)
            
            validate_nfe_configuration(company)
            #validate_invoice_cancel(record)
                
            p = pysped.nfe.ProcessadorNFe()
            
            p.versao = '2.00' if (company.nfe_version == '200') else '1.10'
            p.estado = company.partner_id.l10n_br_city_id.state_id.code
        
            file_content_decoded = base64.decodestring(company.nfe_a1_file)
            p.certificado.stream_certificado = file_content_decoded
            p.certificado.senha = company.nfe_a1_password
    
            p.salva_arquivos = True
            p.contingencia_SCAN = False
            p.caminho = company.nfe_export_folder or os.path.join(expanduser("~"), company.name)
            
            processo = p.cancelar_nota_evento(
                chave_nfe = record.nfe_access_key,
                numero_protocolo=record.nfe_status,
                justificativa='Somente um teste de cancelamento' #TODO Colocar a justificativa de cancelamento num wizard de cancelamento.
            )

            nfe_send_pool = self.pool.get('l10n_br_nfe.send_sefaz')
            nfe_send_id = 0
            if not record.send_nfe_invoice_id:
                nfe_send_id = nfe_send_pool.create(cr, uid, { 'name': 'Envio NFe', 'start_date': datetime.datetime.now()}, context)
                self.write(cr, uid, ids, {'send_nfe_invoice_id': nfe_send_id})
            else:
                nfe_send_id = record.send_nfe_invoice_id.id
                
                
            sucesso = 'Error'
            if processo.resposta.infCanc.cStat.valor == '101':
                sucesso = 'success'
            result_pool = self.pool.get('l10n_br_nfe.send_sefaz_result')
            result_pool.create(cr, uid, {'send_sefaz_id': nfe_send_id , 'xml_type': 'Cancelamento',
                            'name':'Envio_Cancelamento.xml', 'file':base64.b64encode(processo.envio.xml.encode('utf8')),
                            'name_result':'Retorno_Cancelamento.xml', 'file_result':base64.b64encode(processo.resposta.xml.encode('utf8')),
                            'status':sucesso, 'status_code':processo.resposta.infCanc.cStat.valor,
                            'message':processo.resposta.infCanc.xMotivo.valor}, context)
            
        elif record.state in ('sefaz_export','sefaz_exception'):
            result_pool = self.pool.get('l10n_br_account.invoice.invalid.number')
            
            invalidate_number_id = result_pool.create(cr, uid, {'company_id':record.company_id.id,
                'fiscal_document_id':record.fiscal_document_id.id,'document_serie_id':record.document_serie_id.id,
                'number_start':record.internal_number,'number_end':record.internal_number,
                'justificative':'Inutilização originada do cancelamento da fatura: ' + record.internal_number}, context)
            
            invoice_invalidate = result_pool.browse(cr, uid, invalidate_number_id, context)
            invoice_invalidate.action_draft_done(cr, uid, [invalidate_number_id], context) 
    