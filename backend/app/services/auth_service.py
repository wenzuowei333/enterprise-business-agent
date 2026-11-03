"""New local auth adapter: hashed session tokens, revocation and CSRF checks."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from app import models as m
from app.core.config import settings

HASHER=PasswordHasher()
DUMMY_HASH=HASHER.hash('local-demo-dummy-password')
COOKIE='inventory_demo_session'


def get_db(request:Request):
    with request.app.state.session_factory() as db:
        yield db


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def audit(db,user,action,resource_id=None,details=None):
    db.add(m.AuditLog(user_id=user.id if user else None,role_code=user.role if user else None,
                     action_type=action,resource_type='exception_case',resource_id=str(resource_id) if resource_id else None,
                     after_data=details or {}))


def login(db,username,password):
    user=db.scalar(select(m.User).where(m.User.username==username))
    try:
        valid=HASHER.verify(user.password_hash if user else DUMMY_HASH,password)
    except (VerificationError,InvalidHashError):
        valid=False
    if not valid or not user or not user.is_active or user.status!='active':
        audit(db,None,'login_rejected');db.commit()
        raise HTTPException(401,detail={'code':'invalid_credentials','message':'账号或密码不正确，或账号已停用'})
    token=secrets.token_urlsafe(32)
    session=m.DemoSession(token_hash=digest(token),user_id=user.id,csrf_token=secrets.token_urlsafe(24),
                          expires_at=datetime.now(timezone.utc)+timedelta(seconds=settings.session_ttl_seconds))
    db.add(session)
    audit(db,user,'login_succeeded')
    db.commit()
    return user,session,token


def require_user(request:Request,db=Depends(get_db)):
    token=request.cookies.get(COOKIE,'')
    session=db.scalar(select(m.DemoSession).where(m.DemoSession.token_hash==digest(token),
                                                m.DemoSession.expires_at>datetime.now(timezone.utc))) if token else None
    user=db.get(m.User,session.user_id) if session else None
    if not user or not user.is_active or user.status!='active':
        raise HTTPException(401,detail={'code':'login_required','message':'请登录有效演示账号'})
    request.state.demo_session=session
    return user


def require_csrf(request:Request,user=Depends(require_user)):
    sent=request.headers.get('X-CSRF-Token','')
    if not secrets.compare_digest(sent,request.state.demo_session.csrf_token):
        raise HTTPException(403,detail={'code':'csrf_required','message':'请求校验失败，请重新登录'})
    return user
