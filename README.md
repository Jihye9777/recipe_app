# 한입노트

유튜브 영상에서 레시피를 정리하고, 보유 재료와 저장된 레시피를 비교해 메뉴를 추천하는 로컬 MVP입니다.

## 실행

가장 간단한 방법은 `start_app.bat`을 더블클릭하는 것입니다. 열린 창을 유지한 채 브라우저에서 `http://localhost:8000`을 엽니다.

PowerShell에서는 프로젝트 폴더로 이동한 뒤 아래처럼 실행할 수도 있습니다.

```powershell
conda run -n env_recipe python server.py
```

브라우저에서 `http://localhost:8000`을 엽니다.

## 실제 YouTube + AI 분석

서버가 YouTube 공개 자막을 읽고, 항상 Ollama의 로컬 모델로 재료와 조리 순서를 정리합니다. OpenAI API 키는 사용하지 않습니다.

현재 Ollama 모델이 `gemma4:latest`로 설치되어 있어 기본값으로 사용합니다. 다른 모델이면 `OLLAMA_MODEL` 환경 변수로 바꿀 수 있습니다.

PowerShell 예시:

```powershell
conda run -n env_recipe python server.py
```

Ollama가 실행 중이지 않으면 자막 수집까지만 동작하며 앱 화면에서 실행 안내를 보여줍니다. YouTube 자막이 비공개인 영상은 분석할 수 없습니다.
