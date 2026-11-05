"""Local OpenAI-compatible deterministic fixture, never calls an external provider."""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        messages=payload.get('messages',[])
        system='\n'.join(str(x.get('content','')) for x in messages if x.get('role')=='system')
        content='【本地 Mock 演示】当前为完整项目的合成数据环境。请从工作台查看经营摘要、客户项目、销售采购及库存证据；业务变更仍需通过权限校验和人工确认。此回复为固定演示文本，不代表真实模型分析。'
        if 'root_cause_code' in system:
            match=re.search(r'root_cause_code must be selected from: ([a-z_]+)',system)
            code=match[1] if match else 'insufficient_evidence'
            content=json.dumps({'root_cause_code':code,'summary':'本地 Mock 演示：请人工核对规则生成的异常证据。',
                'confidence':0.5,'evidence_refs':[],'impact':'当前仅演示完整应用中的任务与审计流转。',
                'recommended_steps':['核对来源记录后再通过应用发起受控复检。'],
                'missing_evidence':['演示模式未执行真实模型分析。'],'disposition':'blocked'},ensure_ascii=False)
        if payload.get('stream'):
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            chunk={'id':'local-mock','choices':[{'index':0,'delta':{'content':content},'finish_reason':None}]}
            self.wfile.write(('data: '+json.dumps(chunk,ensure_ascii=False)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        else:
            result={'id':'local-mock','model':'local-mock','choices':[{'message':{'role':'assistant','content':content},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}}
            data=json.dumps(result,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)


if __name__ == '__main__':
    ThreadingHTTPServer((os.getenv('MOCK_BIND','127.0.0.1'),int(os.getenv('MOCK_PORT','18209'))),Handler).serve_forever()
