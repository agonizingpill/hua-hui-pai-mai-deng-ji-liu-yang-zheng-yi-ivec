from sqlalchemy import select,func
from .db import Base,engine,Session
from .models import *
from .auth import hashed

def seed():
    Base.metadata.create_all(engine)
    with Session()as s:
        for role in ('operator','supervisor','viewer'):
            if not s.scalar(select(User.id).where(User.email==role+'@chenlu.demo')):s.add(User(email=role+'@chenlu.demo',password_hash=hashed('Flowers2026!'),role=role))
        if not s.get(Clock,1):s.add(Clock(id=1,now='2026-11-18T08:00:00'))
        c=s.scalar(select(Consignment).where(Consignment.code=='FL031'))
        if not c:c=Consignment(code='FL031',grower='露禾花圃',variety='洋桔梗·晨雾白',cut_at='2026-11-18T04:30:00',arrived_at='2026-11-18T07:30:00',crates=18,stems_per_crate=40,note='18筐逐筐验收，筐贴FL031-01至18');s.add(c);s.flush()
        sample=s.scalar(select(VaseSample).where(VaseSample.code=='FLS31'))
        if not sample:sample=VaseSample(consignment_id=c.id,code='FLS31',maturity=.35,stem_cm=72,cold_hours=2,observed_days=6,state='approved',approved_grade='A',review_note='历史已核级签，样本后续观察6天');s.add(sample);s.flush()
        session=s.scalar(select(AuctionSession).where(AuctionSession.code=='HISTORY-031'))
        if not session:session=AuctionSession(code='HISTORY-031',opens_at='2026-11-18T07:40:00',closes_at='2026-11-18T07:50:00');s.add(session);s.flush()
        lot=s.scalar(select(AuctionLot).where(AuctionLot.code=='HIST-LOT031'))
        if not lot:lot=AuctionLot(code='HIST-LOT031',consignment_id=c.id,sample_id=sample.id,session_id=session.id,crates=2,reserve_cents=8000,state='sold',grade_snapshot='A');s.add(lot);s.flush()
        bid=s.scalar(select(Bid).where(Bid.lot_id==lot.id))
        if not bid:bid=Bid(lot_id=lot.id,buyer='巷口花店',unit_cents=10000,at='2026-11-18T07:45:00');s.add(bid);s.flush()
        deal=s.scalar(select(Deal).where(Deal.lot_id==lot.id))
        if not deal:deal=Deal(lot_id=lot.id,bid_id=bid.id,buyer=bid.buyer,crates=2,unit_cents=10000,original_grade='A',effective_grade='A',revision=1,at='2026-11-18T07:50:00');s.add(deal);s.flush()
        if not s.scalar(select(Dispute.id).where(Dispute.deal_id==deal.id)):s.add(Dispute(deal_id=deal.id,reason='历史留样仅6天，买方请求按留样复判',state='opened',sample_snapshot={c.name:getattr(sample,c.name)for c in sample.__table__.columns}))
        # 寿命保守下界把关演示数据：同品种两个历史到场批共10对已封存实测/原估值配对
        def pred(days):return {'model':'GradientBoostingRegressor','seed':35,'vase_days':round(float(days),3),'suggested_grade':'A'if days>=10 else'B'if days>=7 else'C','threshold_days':{'A':10,'B':7,'C':0}}
        hist_ratios=[.92,.88,.83,.79,.75,.95,.86,.80,.77,.90]
        hist_codes=['FL030','FL030B']
        for ci,hcode in enumerate(hist_codes):
            hc=s.scalar(select(Consignment).where(Consignment.code==hcode))
            if not hc:
                hc=Consignment(code=hcode,grower='露禾花圃',variety='洋桔梗·晨雾白',cut_at='2026-11-17T05:00:00',arrived_at='2026-11-17T07:00:00',crates=12,stems_per_crate=40,note='寿命把关历史封存批');s.add(hc);s.flush()
            for k in range(5):
                scode=f'FLS-{hcode}-{k+1}'
                if not s.scalar(select(VaseSample.id).where(VaseSample.code==scode)):
                    ratio=hist_ratios[ci*5+k];est=12.0
                    s.add(VaseSample(consignment_id=hc.id,code=scode,maturity=.4,stem_cm=70,cold_hours=3,
                                     observed_days=round(est*ratio,2),state='approved',approved_grade='A',
                                     prediction=pred(est),review_note='历史已封存瓶插终点，用于同品种误差比对'))
        # 新到场批：已核级A级、未封存；10对配对p10系数0.75，下界8.625天撑不起A级，挂场须主管签字
        c2=s.scalar(select(Consignment).where(Consignment.code=='FL032'))
        if not c2:
            c2=Consignment(code='FL032',grower='露禾花圃',variety='洋桔梗·晨雾白',cut_at='2026-11-18T04:40:00',arrived_at='2026-11-18T07:20:00',crates=16,stems_per_crate=40,note='新批，挂场前走寿命保守下界把关');s.add(c2);s.flush()
        if not s.scalar(select(VaseSample.id).where(VaseSample.code=='FLS32')):
            s.add(VaseSample(consignment_id=c2.id,code='FLS32',maturity=.32,stem_cm=74,cold_hours=2,state='approved',approved_grade='A',
                             prediction=pred(11.5),review_note='本次待挂场留样，模型估值11.5天，核定A级'))
        s.commit();return {m.__tablename__:s.scalar(select(func.count()).select_from(m))for m in (User,Consignment,VaseSample,AuctionSession,AuctionLot,Bid,Deal,Dispute,Settlement,LifeApproval)}
