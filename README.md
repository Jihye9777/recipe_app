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

Ollama 상태는 기본 포트 `11434`에서 확인하며, 앱 상단의 `로컬 AI 연결됨` 표시가 초록색이면 분석에 사용할 수 있는 상태입니다.

PowerShell 예시:

```powershell
conda run -n env_recipe python server.py
```

## 텍스트 추출 순서

1. `youtube-transcript-api`로 한국어 자막을 우선 가져옵니다.
2. 자막을 가져오지 못하면 영상의 오디오만 임시로 받아 로컬 `faster-whisper` 모델로 텍스트화합니다. 첫 실행 때 Whisper 모델을 내려받으므로 시간이 걸릴 수 있습니다.
3. 자동 추출이 모두 되지 않으면 화면의 텍스트 입력란에 스크립트·설명란·메모를 붙여 넣어 Ollama 분석을 실행할 수 있습니다.

## YouTube가 자동 요청을 막을 때

YouTube가 자막 요청을 막거나 자막을 제공하지 않는 영상도 있을 수 있습니다. 이때는 YouTube의 `스크립트 표시`에서 텍스트를 복사해 앱에 붙여 넣으면 됩니다.
