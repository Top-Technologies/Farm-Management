# -*- coding: utf-8 -*-
"""
Helper script to link Dashen Bank accounts to Head Office employees in Odoo 18.
Run after importing head_office_employees_import_ready.csv.

Usage:
  echo "import custom_addons.farm_management.scripts.link_dashen_bank_accounts as s; s.run(env)" | ./odoo-bin shell -c debian/odoo.conf -d hpdb18 --no-http
"""
import csv
import os

CSV_PATH = '/home/toptech/Downloads/head_office_employees_import_ready.csv'

def run(env):
    if not os.path.exists(CSV_PATH):
        print(f"Error: CSV file not found at {CSV_PATH}")
        return

    dashen_bank = env['res.bank'].search([('name', 'ilike', 'Dashen Bank')], limit=1)
    if not dashen_bank:
        dashen_bank = env['res.bank'].create({'name': 'Dashen Bank', 'bic': 'DASHETAA'})
        print("Created Dashen Bank record.")

    with open(CSV_PATH, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            name = (row.get('Name') or '').strip()
            acc_num = (row.get('Bank Account Number (Dashen)') or '').strip()
            if not name or not acc_num:
                continue

            emp = env['hr.employee'].search([('name', '=', name)], limit=1)
            if not emp:
                continue

            partner = emp.work_contact_id
            if not partner:
                partner = env['res.partner'].create({
                    'name': emp.name,
                    'is_company': False,
                    'type': 'private',
                })
                emp.work_contact_id = partner.id

            bank_acc = env['res.partner.bank'].search([
                ('acc_number', '=', acc_num),
                ('partner_id', '=', partner.id)
            ], limit=1)

            if not bank_acc:
                bank_acc = env['res.partner.bank'].create({
                    'acc_number': acc_num,
                    'partner_id': partner.id,
                    'bank_id': dashen_bank.id,
                    'acc_holder_name': emp.name,
                })

            if emp.bank_account_id.id != bank_acc.id:
                emp.bank_account_id = bank_acc.id
                count += 1
                print(f"[{count}] Linked Dashen Bank {acc_num} -> {emp.name}")

    env.cr.commit()
    print(f"\nSuccessfully verified and linked {count} bank accounts to employees!")
