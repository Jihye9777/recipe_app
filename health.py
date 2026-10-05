"""Read-only service readiness checks (never create collections or download models)."""
import os
import requests

def service_health(store, index):
    """앱 구성 요소의 읽기 전용 준비 상태를 한 번에 검사한다.

    Args:
        store: ``connect``와 ``needs_index``를 제공하는 SQLite 저장소.
        index: ``health``, ``backend``를 제공하는 벡터 인덱스 인스턴스.

    Returns:
        ``sqlite``, ``ollama``, ``embedding``, ``qdrant``별 상태와 전체
        ``ready``를 포함한 사전. Qdrant 상태에는 현재 백엔드·임베딩 모델로
        다시 색인해야 하는 레시피 수인 ``needsReindex``도 포함된다.

    Notes:
        이 함수는 모델을 다운로드하거나 컬렉션을 생성하지 않는다. SQLite
        행 수, Ollama ``/api/tags``, Qdrant 메타데이터만 읽는다. 개별 검사
        실패는 예외로 전파하지 않고 해당 구성 요소의 ``error``에 기록한다.
    """
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
