# 한입노트

유튜브 영상에서 레시피를 정리하고, 보유 재료와 저장된 레시피를 비교해 메뉴를 추천하는 로컬 MVP입니다.

## 실행

가장 간단한 방법은 `start_app.bat`을 더블클릭하는 것입니다. 열린 창을 유지한 채 브라우저에서 `http://localhost:8000`을 엽니다.

PowerShell에서는 프로젝트 폴더로 이동한 뒤 아래처럼 실행할 수도 있습니다.

```powershell
conda run -n env_recipe python server.py
```

브라우저에서 `http://localhost:8000`을 엽니다.

현재 YouTube 분석은 화면 흐름을 확인하기 위한 데모입니다. 실제 영상 자막·음성 분석은 API 연동 단계에서 추가할 수 있습니다.
