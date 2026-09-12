"""Read-only service readiness checks (never create collections or download models)."""
import os
from socket import create_connection
import requests

def service_health(store):
    result={}
    try:
        with store.connect() as db:
            count=db.execute('SELECT COUNT(*) FROM recipes').fetchone()[0]
        result['sqlite']={'ready':True,'recipes':count}
    except Exception as e: result['sqlite']={'ready':False,'error':str(e)}
    model=os.getenv('OLLAMA_MODEL','gemma4:latest')
    embedding=os.getenv('EMBEDDING_MODEL','embeddinggemma')
    try:
        response=requests.get(os.getenv('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')+'/api/tags',timeout=(2,3))
        response.raise_for_status(); names={x['name'] for x in response.json().get('models',[])}
        installed=lambda name: name in names or (':' not in name and name+':latest' in names)
        result['ollama']={'ready':installed(model),'model':model}
        result['embedding']={'ready':installed(embedding),'model':embedding}
    except Exception as e:
        result['ollama']={'ready':False,'model':model,'error':str(e)}
        result['embedding']={'ready':False,'model':embedding}
    try:
        url='http://'+os.getenv('WEAVIATE_HOST','127.0.0.1')+':'+os.getenv('WEAVIATE_HTTP_PORT','8080')+'/v1/.well-known/ready'
        response=requests.get(url,timeout=(2,3));response.raise_for_status()
        with create_connection((os.getenv('WEAVIATE_HOST','127.0.0.1'),int(os.getenv('WEAVIATE_GRPC_PORT','50051'))),timeout=2):
            pass
        result['weaviate']={'ready':True}
    except Exception as e:result['weaviate']={'ready':False,'error':str(e)}
    result['ready']=all(result[k]['ready'] for k in ('sqlite','ollama','embedding','weaviate'))
    return result
