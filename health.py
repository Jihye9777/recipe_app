"""Read-only service readiness checks (never create collections or download models)."""
import os
import requests

def service_health(store, index):
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
    try: result['qdrant']=index.health()
    except Exception as e:result['qdrant']={'ready':False,'backend':'qdrant-local','error':str(e)}
    try: result['qdrant']['needsReindex']=len(store.needs_index(index.backend,embedding))
    except Exception: result['qdrant']['needsReindex']=None
    result['ready']=all(result[k]['ready'] for k in ('sqlite','ollama','embedding','qdrant'))
    return result
