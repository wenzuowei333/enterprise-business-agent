"""Synthetic full-application fixtures; never import original business data."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.engine import make_url
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app import models as m
from app.services.seed_stage1 import seed_stage1
from app.services.exception_center_service import default_policy
from urllib.parse import urlparse


def main():
    url = make_url(settings.database_url)
    if (settings.environment != 'demo' or url.database not in {'erp_full_demo', 'portfolio_erp_full'}
        or url.username != 'portfolio_demo' or url.host not in {'127.0.0.1', 'localhost', 'db'}
        or url.port not in {None, 5432, 18432} or url.query):
        raise SystemExit('Refusing to seed anything except the dedicated local full demo database')
    today = date(2026, 11, 5)
    now = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)
    with SessionLocal() as db:
        seed_stage1(db)
        if urlparse(settings.hermes_api_base_url or '').hostname not in {'mock', '127.0.0.1', 'localhost'}:
            raise SystemExit('Full demo requires the bundled local Mock provider')
        policy=default_policy(db)
        if not (policy.settings_json or {}).get('full_demo_initialized'):
            policy.is_enabled=True
            policy.manual_ai_enabled=True
            policy.manual_ai_daily_limit=100
            policy.settings_json={**(policy.settings_json or {}), 'full_demo_initialized':True}
            db.commit()
        if db.scalar(select(m.CustomerMaster).where(m.CustomerMaster.customer_code == 'DEMO-C001')):
            print({'synthetic': True, 'existing_demo_preserved': True})
            return
        admin = db.scalar(select(m.User).where(m.User.username == settings.initial_admin_username))
        staff = []
        for i, (username, name, role) in enumerate([
            ('demo_sales', '演示业务员甲', 'salesperson'),
            ('demo_manager', '演示业务经理', 'business_middle_office'),
            ('demo_viewer', '演示只读账号', 'viewer'),
        ], 1):
            user=m.User(username=username, real_name=name, employee_code=f'DEMO-E{i:03}',
                        password_hash=hash_password('LocalDemo-2026!'), role=role, status='active', is_active=True)
            db.add(user);db.flush();staff.append(user)
            db.add(m.EmployeeProfile(employee_code=user.employee_code, employee_name=name,
                                    user_id=user.id, department='演示业务部', position='业务协作', role_code=role, status='active'))
        regions=['演示华东区','演示华南区','演示华北区']
        customers=[]
        for i in range(1,31):
            c=m.CustomerMaster(customer_code=f'DEMO-C{i:03}',customer_name=f'虚构客户{i:02}号商贸',
                customer_short_name=f'演示客户{i:02}',customer_type='经销商',region=regions[i%3],
                salesperson_employee_code=staff[0].employee_code,salesperson_name=staff[0].real_name,
                contact_name=f'虚构联系人{i:02}',contact_channel='demo@example.invalid',
                customer_tags=['合成数据','演示客户'],address=f'虚构城市演示路{i}号',source='synthetic_demo')
            db.add(c);db.flush();customers.append(c)
            db.add(m.CustomerBusinessProfile(customer_code=c.customer_code,customer_name_snapshot=c.customer_name,
                business_customer_type='经销商',confirmed_at=today,current_salesperson=staff[0].real_name,
                sales_channels=['线下批发'],business_status_tags=['正常合作'],business_status_label='正常合作',
                latest_update_note='为完整项目展示创建的虚构经营资料',version_no=1))
        products=[]
        for i,(name,unit) in enumerate([('虚构青绿随行杯','个'),('虚构桌面收纳盒','个'),('虚构便携餐盒','个'),
                ('虚构折叠购物袋','只'),('虚构厨房清洁布','包'),('虚构保温水壶','个'),('虚构整理篮','个'),('虚构纸巾盒','个')],1):
            p=m.ProductMaster(product_code=f'DEMO-P{i:03}',product_name=name,spec='标准演示规格',unit=unit,
                category='演示日用百货',brand='DEMO LAB',reference_sale_price=Decimal(20+i*5),reference_cost=Decimal(12+i*3),source='synthetic_demo')
            db.add(p);products.append(p)
        suppliers=[]
        for i in range(1,5):
            s=m.SupplierMaster(supplier_code=f'DEMO-S{i:03}',supplier_name=f'虚构供应商{i:02}号',
                supplier_type='演示工厂',region=regions[i%3],contact_name=f'演示供应联系人{i}',source='synthetic_demo')
            db.add(s);suppliers.append(s)
        db.flush()
        batches={}
        for kind,count in [('sales_detail',90),('purchase_detail',24),('inventory_snapshot',16),('account_balance',12),('account_ledger',12)]:
            b=m.ImportBatch(batch_no=f'DEMO-{kind.upper()}',file_name=f'synthetic-{kind}.xlsx',file_type=kind,
                data_date=today,export_date=today,uploaded_by=admin.id,status='committed',total_rows=count,
                success_rows=count,error_rows=0,raw_file_path=f'demo/synthetic-{kind}.xlsx')
            db.add(b);db.flush();batches[kind]=b
        for i in range(90):
            c=customers[i%len(customers)];p=products[i%len(products)];qty=Decimal(5+i%12);price=p.reference_sale_price
            when=today-timedelta(days=i%35);amount=qty*price;cost=qty*p.reference_cost
            db.add(m.SalesDetail(batch_id=batches['sales_detail'].id,row_number=i+1,data_date=when,
                document_no=f'DEMO-SALE-{i+1:04}',document_date=when,document_type='销售单',
                customer_code=c.customer_code,customer_name=c.customer_name,settlement_unit_code=c.customer_code,
                settlement_unit_name=c.customer_name,employee_name=staff[0].real_name,warehouse_name='演示中心仓',
                product_code=p.product_code,product_name=p.product_name,sale_qty_base=qty,amount_before_discount=amount,
                unit_price_after_discount=price,amount_after_discount=amount,amount_tax_total=amount,cost_amount=cost,
                gross_profit=amount-cost,gross_margin_rate=(amount-cost)/amount,summary='合成销售记录'))
        for i in range(24):
            s=suppliers[i%4];p=products[i%8];qty=Decimal(30+i);amount=qty*p.reference_cost
            db.add(m.PurchaseDetail(batch_id=batches['purchase_detail'].id,row_number=i+1,data_date=today,
                document_no=f'DEMO-BUY-{i+1:04}',document_date=today,document_type='采购单',
                supplier_code=s.supplier_code,supplier_name=s.supplier_name,product_code=p.product_code,
                product_name=p.product_name,warehouse_name='演示中心仓',purchase_qty_base=qty,
                unit_price=p.reference_cost,amount_after_discount=amount,purchase_amount=amount,summary='合成采购记录'))
        for i in range(16):
            p=products[i%8];qty=Decimal(-3 if i==0 else 10+i*3)
            db.add(m.InventorySnapshot(batch_id=batches['inventory_snapshot'].id,row_number=i+1,data_date=today,
                product_code=p.product_code,product_name=p.product_name,warehouse_name='演示中心仓' if i<8 else '演示分仓',
                warehouse_scope='main' if i<8 else 'branch',stock_qty=qty,stock_inventory_qty=qty,stock_base_unit=p.unit,
                locked_base_qty=Decimal(100 if i==1 else 2),average_cost=p.reference_cost,cost_amount=qty*p.reference_cost))
        for i,c in enumerate(customers[:12],1):
            amount=Decimal(300+i*110)
            db.add(m.AccountBalanceSnapshot(batch_id=batches['account_balance'].id,row_number=i,data_date=today,
                balance_date=today,settlement_unit_code=c.customer_code,settlement_unit_name=c.customer_name,
                ar_balance=amount,ap_balance=Decimal(0),current_closing_balance=amount))
            db.add(m.AccountLedgerEntry(batch_id=batches['account_ledger'].id,row_number=i,data_date=today,
                settlement_unit_code=c.customer_code,settlement_unit_name=c.customer_name,document_no=f'DEMO-LEDGER-{i:03}',
                document_type='期末',document_date=today,document_amount=amount,ar_amount=amount,
                received_amount=Decimal(0),current_balance=amount,balance_date=today,
                period_start=today.replace(day=1),period_end=today,summary='合成往来记录',row_role='closing'))
        for i in range(1,9):
            db.add(m.CrmLead(lead_no=f'DEMO-LEAD-{i:03}',lead_name=f'虚构潜在客户{i:02}',normalized_name=f'demo-lead-{i}',
                company_name=f'虚构潜在客户{i:02}',contact_name=f'演示联系人{i}',source='展会演示',region=regions[i%3],
                intent_summary='了解演示日用百货产品与合作条件',status='active',priority='high' if i%3==0 else 'normal',
                owner_user_id=staff[0].id,assigned_user_id=staff[0].id,created_by_user_id=admin.id))
        for i,title in enumerate(['演示新品渠道拓展','演示老客复购推进','演示重点客户拜访'],1):
            project=m.CrmProject(project_code=f'DEMO-PRJ-{i:03}',project_name=title,project_type='客户开发',
                purpose='通过合成客户演示项目、任务与跟进协作',applicant_user_id=staff[1].id,owner_user_id=staff[1].id,
                project_manager_user_id=staff[1].id,participant_user_ids=[staff[0].id],start_date=today-timedelta(days=7),
                due_date=today+timedelta(days=14),minimum_action='记录一次客户沟通',closure_standard='完成需求确认',
                status='in_progress',approval_status='approved',created_by_user_id=admin.id)
            db.add(project);db.flush()
            for j,c in enumerate(customers[(i-1)*4:i*4],1):
                task=m.CrmProjectCustomerTask(project_id=project.id,task_code=f'DEMO-TASK-{i}-{j}',
                    customer_code=c.customer_code,customer_name_snapshot=c.customer_name,executor_user_id=staff[0].id,
                    executor_employee_code=staff[0].employee_code,executor_name_snapshot=staff[0].real_name,
                    business_issue_point='确认产品需求与交付周期',round_target='完成需求沟通',feedback_due_at=now+timedelta(days=j-2),
                    status='not_started' if j>2 else 'in_progress')
                db.add(task);db.flush()
                if j<=2:
                    follow=m.CrmFollowup(followup_no=f'DEMO-FOLLOW-{i}-{j}',project_id=project.id,task_id=task.id,
                        customer_code=c.customer_code,executor_user_id=staff[0].id,executor_name_snapshot=staff[0].real_name,
                        followup_date=today,method='电话',frontline_action='介绍演示新品与合作方案',
                        customer_feedback='对样品感兴趣，等待确认规格',current_need='产品资料与样品',
                        next_action='安排演示样品确认',next_followup_at=now+timedelta(days=2),review_status='pending')
                    db.add(follow);db.flush();task.latest_followup_id=follow.id;task.last_followup_at=now
            approval=m.ApprovalInstance(approval_no=f'DEMO-AP-{i:03}',approval_type='crm_project_create',resource_type='crm_project',
                resource_id=str(project.id),title=f'{title}：演示审批',description='完整项目演示用虚构审批记录',
                applicant_user_id=staff[1].id,current_handler_user_id=admin.id,status='submitted',submitted_at=now)
            db.add(approval)
            db.add(m.WorkItem(item_no=f'DEMO-WORK-{i:03}',source_type='demo',source_id=str(project.id),
                project_id=project.id,item_type='support',title=f'{title}：准备样品资料',detail='合成协作待办',
                assignee_user_id=staff[1].id,due_at=now+timedelta(days=2),priority='normal',status='open'))
        db.commit()
        print({'synthetic': True, 'customers': 30, 'products': 8, 'suppliers': 4, 'sales': 90,
               'purchases': 24, 'inventory': 16, 'crm_projects': 3, 'crm_tasks': 12, 'crm_leads': 8})


if __name__ == '__main__':
    main()
