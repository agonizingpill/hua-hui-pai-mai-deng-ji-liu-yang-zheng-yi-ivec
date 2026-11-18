import hashlib,math
from sqlalchemy import select
from fastapi import HTTPException
from .models import Consignment,VaseSample,LifeApproval,Clock
from .common import lock,pack,add,audit

# 寿命等级门槛与争议复判口径一致：A≥10天、B≥7天、否则C
GRADE_MIN_DAYS={'A':10.0,'B':7.0,'C':0.0}
MIN_PAIRS=10          # 同品种其他到场批的封存配对少于该数，须主管签字
CONSERVATIVE_Q=0.10   # 取误差分布的第10百分位，作为九成保守系数

def lock_variety(s,variety):
    # 同品种全部到场父行按id顺序加锁：封存与挂场据此串行化，避免检查窗口
    rows=s.scalars(select(Consignment).where(Consignment.variety==variety).order_by(Consignment.id).with_for_update()).all()
    if not rows:raise HTTPException(404,'该品种无到场批次记录')
    return rows

def _estimate_days(sample):
    pred=sample.prediction
    if isinstance(pred,dict):
        value=pred.get('vase_days')
        if isinstance(value,(int,float))and math.isfinite(value):return float(value)
    return None

def _nearest_rank(values,q):
    # 最近秩百分位（确定性，不插值）：rank=ceil(q*n)，取第rank小
    ordered=sorted(values)
    idx=max(1,math.ceil(q*len(ordered)))-1
    return ordered[idx]

def _basis_hash(pairs,lower_bound,grade):
    h=hashlib.sha256()
    for p in pairs:
        h.update(f"{p['sample_id']}:{p['observed_days']}:{p['estimate_days']}|".encode())
    h.update(f"#lb={lower_bound}#g={grade}".encode())
    return h.hexdigest()

def build_guard(s,sample):
    cons=s.get(Consignment,sample.consignment_id)
    if not cons:raise HTTPException(404,'留样对应的到场批次不存在')
    estimate=_estimate_days(sample)
    rows=s.scalars(select(VaseSample).join(Consignment,VaseSample.consignment_id==Consignment.id).where(
        Consignment.variety==cons.variety,
        Consignment.id!=cons.id,
        VaseSample.observed_days.isnot(None))).all()
    pairs=[]
    for r in rows:
        est=_estimate_days(r)
        if est is None or est<=0:continue  # 无原估值或估值异常的封存记录无法计算误差
        pairs.append({'sample_id':r.id,'sample_code':r.code,'consignment_code':s.get(Consignment,r.consignment_id).code,
                      'observed_days':r.observed_days,'estimate_days':round(est,3),'ratio':round(r.observed_days/est,4)})
    pairs.sort(key=lambda p:p['sample_id'])
    pair_count=len(pairs)
    factor=lower=None
    if pair_count>=MIN_PAIRS:
        factor=round(_nearest_rank([p['ratio'] for p in pairs],CONSERVATIVE_Q),4)
        lower=round(estimate*factor,3) if estimate is not None else None
    grade=sample.approved_grade
    blockers=[]
    if sample.state!='approved' or not grade:
        blockers.append('留样尚未主管核定等级，不能挂场')
    if estimate is None:
        blockers.append('留样缺少原寿命估值，无法计算保守下界')
    if pair_count<MIN_PAIRS:
        blockers.append(f'同品种其他到场批封存配对仅{pair_count}对，不足{MIN_PAIRS}对')
    if lower is not None and grade and lower<GRADE_MIN_DAYS[grade]:
        blockers.append(f'保守下界{lower}天撑不起核定{grade}级（门槛{GRADE_MIN_DAYS[grade]:g}天）')
    need_signature=pair_count<MIN_PAIRS or (lower is not None and grade and lower<GRADE_MIN_DAYS[grade])
    basis_hash=_basis_hash(pairs,lower,grade or '')
    approval=s.scalar(select(LifeApproval).where(LifeApproval.sample_id==sample.id).order_by(LifeApproval.id.desc()).limit(1))
    approval_pack=pack(approval) if approval else None
    approval_valid=bool(approval and approval.pair_count==pair_count and approval.lower_bound_days==lower
                        and approval.basis_hash==basis_hash and approval.approved_grade==(grade or ''))
    if approval and not approval_valid:
        blockers.append('原主管签字所依据的封存数据已变化，旧签字失效')
    if blockers and need_signature and approval_valid:
        # 有效主管签字覆盖“样本不足/下界不达标”，但不覆盖核级缺失等硬性拦截
        blockers=[b for b in blockers if not (b.startswith('同品种')or b.startswith('保守下界'))]
    return {'sample_id':sample.id,'sample_code':sample.code,'variety':cons.variety,'approved_grade':grade,
            'estimate_days':round(estimate,3) if estimate is not None else None,
            'pair_count':pair_count,'min_pairs':MIN_PAIRS,'conservative_quantile':CONSERVATIVE_Q,
            'factor_days':factor,'lower_bound_days':lower,'grade_min_days':GRADE_MIN_DAYS.get(grade),
            'need_signature':need_signature,'block_reasons':blockers,
            'latest_approval':approval_pack,'approval_valid':approval_valid,'pairs':pairs,'basis_hash':basis_hash}

def enforce_guard(s,sample,consignment_id=None):
    if consignment_id is not None and sample.consignment_id!=consignment_id:
        raise HTTPException(409,'挂场留样必须属于所选到场批次')
    g=build_guard(s,sample)
    if g['block_reasons']:
        raise HTTPException(409,'寿命把关拦截占筐：'+'；'.join(g['block_reasons']))
    return g

def sign(s,id,d,u):
    pre=s.get(VaseSample,id)
    if not pre:raise HTTPException(404,'留样不存在')
    cons=s.get(Consignment,pre.consignment_id)
    lock_variety(s,cons.variety)  # 与挂场/封存同一锁序：品种行 → 留样行
    sample=lock(s,VaseSample,id)
    g=build_guard(s,sample)
    if sample.state!='approved' or not g['approved_grade']:
        raise HTTPException(409,'先完成主管核定等级，再签寿命把关')
    if not g['need_signature']:
        raise HTTPException(409,'配对数量与保守下界均满足挂场要求，无需额外签字')
    if g['latest_approval'] and g['approval_valid']:
        raise HTTPException(409,'已存在有效主管签字，无需重复签署')
    x=LifeApproval(sample_id=sample.id,supervisor_email=u.email,note=d.note,pair_count=g['pair_count'],
                   lower_bound_days=g['lower_bound_days'],basis_hash=g['basis_hash'],
                   approved_grade=g['approved_grade'],at=lock(s,Clock,1).now)
    audit(s,u,'主管签署寿命保守下界把关 '+sample.code);return add(s,x)
