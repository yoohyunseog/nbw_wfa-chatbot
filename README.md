# nb_wfa-chatbot

네이버 개인 블로그 자동 작성 챗봇 (코드 공유용)

## ⚠️ 주의사항

이 프로젝트는 **코드 공유 목적**으로 제공되며, 실제 실행을 위해서는 다음이 필요합니다:

- 네이버 블로그 계정 및 로그인 세션
- OpenAI API 키
- 기타 외부 서비스 연동 (MySQL, 이미지 호스팅 등)
- 로컬 환경 설정 및 의존성 패키지 설치

**현재 상태로는 바로 실행할 수 없으며, 참고용 코드입니다.**

## 📋 프로젝트 개요

네이버 개인 블로그에 자동으로 포스트를 작성하는 챗봇 시스템입니다. GPT를 활용하여 블로그 글을 생성하고, 검색 엔진 링크(Bing, Naver, Google)를 자동으로 삽입하는 기능을 제공합니다.

## 🎯 주요 기능

### 1. 블로그 글 자동 생성
- GPT를 활용한 블로그 포스트 자동 작성
- 섹션별 구조화된 콘텐츠 생성
- 이미지 프롬프트 자동 생성

### 2. 검색 엔진 링크 삽입
- **Bing, Naver, Google** 검색 링크 선택 가능
- 핵심 키워드에 자동으로 검색 링크 연결
- 검색 엔진별 표준 URL 형식 지원

### 3. 네이버 블로그 연동
- 네이버 블로그 자동 업로드
- 카테고리 자동 분류
- HTML 형식 콘텐츠 지원

## 📁 파일 구조

```
.
├── gpt_chat_interface.py          # 메인 UI 및 블로그 생성 로직
├── prompt_functions.py            # 프롬프트 생성 함수 (검색 엔진 지원)
├── prompt_utils.py                # 프롬프트 유틸리티 함수
├── utils.py                       # 유틸리티 함수 (검색 링크 생성 등)
└── blog_html_generator/
    └── blog_generator_gpt_style.py # 블로그 생성기 (검색 엔진 지원)
```

## 🔧 주요 파일 설명

### `gpt_chat_interface.py`
- PyQt5 기반 GUI 애플리케이션
- 블로그 글 생성 및 네이버 블로그 업로드 기능
- 검색 엔진 선택 UI (Bing, Naver, Google)
- 설정 저장/로드 기능

### `prompt_functions.py` / `prompt_utils.py`
- GPT 프롬프트 생성 함수
- 검색 엔진별 링크 생성 지원
- 섹션별 블로그 콘텐츠 생성

### `utils.py`
- `generate_search_link()`: 검색 엔진별 링크 생성 함수
  ```python
  generate_search_link(keyword, search_engine="bing")
  # search_engine: "bing", "naver", "google"
  ```

### `blog_generator_gpt_style.py`
- 블로그 생성기 클래스
- 웹 데이터 수집 및 콘텐츠 생성
- 검색 엔진 링크 자동 삽입

## 🔍 검색 엔진 링크 기능

### 지원하는 검색 엔진
- **Bing**: `https://www.bing.com/search?q={검색어}&sendquery=1&FORM=SCCODX&rh=B0D80A4F&ref=rafsrchae`
- **Naver**: `https://search.naver.com/search.naver?query={검색어}`
- **Google**: `https://www.google.com/search?q={검색어}`

### 사용 방법
1. UI에서 검색 엔진 선택 (Bing, Naver, Google)
2. 블로그 글 생성 시 선택된 검색 엔진의 링크가 자동으로 삽입됨
3. 핵심 키워드에 검색 링크가 자동 연결됨

## ⚙️ 설정

### API 키 설정
코드에서 하드코딩된 API 키는 제거되어 있습니다. 다음 방법 중 하나로 설정하세요:

1. **환경 변수 사용**:
   ```bash
   set OPENAI_API_KEY=your_api_key_here
   ```

2. **설정 파일 사용**:
   프로젝트 루트에 `openai_config.json` 파일 생성:
   ```json
   {
     "api_key": "your_api_key_here"
   }
   ```

### 설정 파일 (`gpt_blog_config.json`)
- `search_engine`: 기본 검색 엔진 설정 ("bing", "naver", "google")
- 기타 블로그 생성 관련 설정

## 📦 의존성

이 프로젝트는 다음 패키지들을 사용합니다 (실제 설치 여부는 확인 필요):

- `PyQt5`: GUI 프레임워크
- `openai`: OpenAI API 클라이언트
- `selenium`: 웹 자동화 (네이버 블로그 업로드)
- `beautifulsoup4`: HTML 파싱
- `requests`: HTTP 요청
- 기타 프로젝트별 의존성

## 🚫 제한사항

1. **네이버 블로그 로그인 세션 필요**: 실제 업로드를 위해서는 네이버 계정 로그인이 필요합니다.
2. **외부 서비스 의존**: MySQL, 이미지 호스팅 등 외부 서비스가 필요할 수 있습니다.
3. **로컬 환경 설정**: 각자의 환경에 맞게 설정 파일 및 경로를 수정해야 합니다.
4. **API 키 필요**: OpenAI API 키가 필요합니다.

## 📝 코드 공유 목적

이 저장소는 다음을 목적으로 합니다:

- 검색 엔진 링크 삽입 기능 구현 방법 공유
- 블로그 자동 생성 로직 참고
- GPT 프롬프트 생성 패턴 학습
- 네이버 블로그 자동화 아이디어 공유

## ⚠️ 면책 조항

- 이 코드는 교육 및 참고 목적으로 제공됩니다.
- 실제 사용 시 네이버 블로그 이용약관을 준수해야 합니다.
- 자동화 도구 사용에 대한 책임은 사용자에게 있습니다.
- API 키 및 개인정보 보호에 주의하세요.

## 📄 라이선스

이 프로젝트는 코드 공유 목적으로 제공되며, 자유롭게 참고 및 수정 가능합니다.

## 🔗 관련 링크

- [GitHub 저장소](https://github.com/yoohyunseog/nbw_wfa-chatbot)

---

**참고**: 이 프로젝트는 네이버 개인 블로그 자동화를 위한 코드 샘플이며, 실제 실행을 위해서는 추가 설정 및 환경 구성이 필요합니다.

