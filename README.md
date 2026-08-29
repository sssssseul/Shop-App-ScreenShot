# Screen Archive

폰에서 캡처한 스크린샷을 날짜별 타임라인 + 갤러리로 관리하는 개인 아카이브 웹앱.

## 기능
- **타임라인**: 날짜별로 캡처 세션을 묶어서 보여줌 (archive.org 캘린더처럼)
- **갤러리**: 전체 캡처를 그리드로 최신순 나열
- **업로드**: 제목 + 날짜/시각 + 이미지 여러 장(같은 세션으로 묶임) 업로드
- 이미지는 파일이 아니라 **PostgreSQL DB 안에 직접 저장**됨 (Render 무료 티어는 재배포 시 파일시스템이 초기화되기 때문)

## 배포 방법 (Render + PostgreSQL)

1. GitHub에 새 저장소 만들고 이 폴더의 파일들을 웹 인터페이스로 업로드
   (app.py, requirements.txt, templates/, static/)
2. Render 대시보드에서:
   - **PostgreSQL** 인스턴스 하나 생성 (무료 티어)
   - **Web Service** 생성 → 방금 만든 GitHub 저장소 연결
3. Web Service 환경변수(Environment) 설정:
   - `DATABASE_URL` = PostgreSQL의 **Internal Database URL** 값 붙여넣기
   - `PYTHON_VERSION` = `3.11.9`
   - `SECRET_KEY` = 아무 랜덤 문자열
4. Start Command: `gunicorn app:app`
5. 배포 완료되면 URL 접속 → 첫 접속 시 테이블 자동 생성됨 (`init_db()`가 앱 시작 시 실행)

## 로컬에서 테스트하려면

```
pip install -r requirements.txt
export DATABASE_URL="postgresql://...(Render External Database URL)"
python app.py
```

`http://localhost:5000` 접속.

## 참고
- 인증(로그인) 없이 URL만 알면 누구나 접근 가능한 구조입니다. 혼자 쓰는 용도로 충분하지만,
  외부 노출이 꺼려지면 나중에 간단한 비밀번호 보호를 추가할 수 있어요.
- 업로드 시 선택한 이미지 파일 순서 그대로 "세션"으로 묶여 저장됩니다 (여러 장 스크롤 캡처를 한 세트로 관리하기 위함).
