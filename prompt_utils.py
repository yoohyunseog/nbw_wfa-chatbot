"""
GPT 프롬프트 생성 관련 유틸리티 함수들
"""

import re
import json
from datetime import datetime


# 카테고리 목록 정의
CATEGORY_LIST = [
    {"ca_name": "AMERICAAI", "ca_description": "미국 중심의 AI 정책, 기술 동향 및 국가 전략 분석, 미국 관련 모든 소식"},
    {"ca_name": "EUAI", "ca_description": "유럽연합 AI 규제, 윤리적 기준 및 EU AI Act 관련 정보"},
    {"ca_name": "Organizers", "ca_description": "행사 주최자 및 조직 관련 트렌드 및 인물 정보"},
    {"ca_name": "Courses", "ca_description": "온라인/오프라인 교육 과정 및 학습 커리큘럼 정보"},
    {"ca_name": "DramaDetails", "ca_description": "국내외 드라마의 줄거리, 배우 정보 및 시청 트렌드"},
    {"ca_name": "anime", "ca_description": "일본 애니메이션 신작 정보, 리뷰, 팬덤 반응, 웹툰"},
    {"ca_name": "GameNews", "ca_description": "국내외 최신 게임 소식 및 업데이트 정보"},
    {"ca_name": "PokemonBread", "ca_description": "포켓몬빵 굿즈, 띠부띠부씰 및 수집 정보"},
    {"ca_name": "EconomicIndicators", "ca_description": "주요 경제 지표 및 글로벌 금융 동향"},
    {"ca_name": "entertainment", "ca_description": "연예계 전반의 뉴스, 이슈, 스타 동향"},
    {"ca_name": "entertainmentnews", "ca_description": "연예계 속보 중심의 뉴스 콘텐츠"},
    {"ca_name": "movie", "ca_description": "신작 영화, 박스오피스, 감독 및 배우 정보"},
    {"ca_name": "sports", "ca_description": "국내외 스포츠 경기 결과 및 선수 이슈"},
    {"ca_name": "car", "ca_description": "자동차 출시, 시승기, 브랜드 비교 정보"},
    {"ca_name": "TourSpots", "ca_description": "국내외 여행지 추천, 체험기 및 관광 정보"},
    {"ca_name": "robot", "ca_description": "로봇 기술, 산업 동향 및 생활 속 로봇 활용, 컴퓨터 부품 포함"},
    {"ca_name": "politics", "ca_description": "국내외 정치 뉴스 및 정책 분석"},
    {"ca_name": "RecommendedVideo", "ca_description": "AI 기반 추천 영상 및 유튜브 핫 콘텐츠"},
    {"ca_name": "x_file", "ca_description": "미스터리, 음모론, UFO 등 기이한 정보 콘텐츠"},
    {"ca_name": "8bit", "ca_description": "복고풍 8비트 게임, 아트, 음악 관련 콘텐츠"},
    {"ca_name": "UserQueryLog", "ca_description": "사용자 질의 기반 추천 키워드 및 분석 결과"},
    {"ca_name": "CosmeticBrandsInfo", "ca_description": "화장품 브랜드별 트렌드, 제품 리뷰 정보"},
    {"ca_name": "FashionMakersList", "ca_description": "국내외 패션 디자이너 및 브랜드 정보"},
    {"ca_name": "mobilegame", "ca_description": "모바일 게임 출시 정보 및 사용자 리뷰"},
    {"ca_name": "DongmyoFashionHub", "ca_description": "동묘 패션 트렌드, 거리 패션 및 인기 상품 정보"},
    {"ca_name": "stock", "ca_description": "주식시장 동향, 종목 분석 및 투자 전략"},
    {"ca_name": "googleApp", "ca_description": "Google Play 앱 추천, 리뷰 및 순위 정보"},
    {"ca_name": "googleBook", "ca_description": "Google 도서 플랫폼 기반 추천 책 및 분석"},
    {"ca_name": "googleKids", "ca_description": "Google Kids용 콘텐츠, 교육 앱 정보"},
    {"ca_name": "googleComics", "ca_description": "Google 플랫폼 기반 웹툰/코믹스 콘텐츠 소개"},
    {"ca_name": "Semiraepaong", "ca_description": "세미라에파옹 관련 이슈 또는 특정 기획 콘텐츠"},
    {"ca_name": "LiveGameStreams", "ca_description": "실시간 게임 스트리밍 채널 및 인기 클립"},
    {"ca_name": "PsychologyResources", "ca_description": "심리학 기반 리소스, 테스트, 정신 건강 콘텐츠"},
    {"ca_name": "CommGuide", "ca_description": "지역 커뮤니티 안내, 이용 규칙, 운영 가이드"},
    {"ca_name": "usa", "ca_description": "미국 사회, 경제, 문화 관련 트렌드와 분석"},
    {"ca_name": "afreecatv", "ca_description": "아프리카TV 인기 방송, BJ 트렌드 및 콘텐츠 분석"}
]


def get_category_json():
    """카테고리 목록을 JSON 형태로 반환"""
    return json.dumps(CATEGORY_LIST, ensure_ascii=False, indent=2)


def sanitize_prompt(text: str) -> str:
    """텍스트에서 널문자 제거 및 길이 제한"""
    return text.replace('\x00', '').strip()[:8000]


def safe_json_parse(response_text: str, step_name="STEP"):
    """안전한 JSON 파싱"""
    if not response_text or not response_text.strip():
        raise ValueError(f"❌ {step_name} GPT 응답이 비어 있습니다.")

    cleaned = re.sub(r"^```(json)?", "", response_text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()

    if cleaned.startswith("<h2>") or cleaned.startswith("<p>"):
        return {
            "content": cleaned
        }

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"❌ {step_name} JSON 파싱 실패: {e}")
        print("📄 응답 원문 ↓↓↓\n", cleaned)
        raise


def build_article_from_existing_structure(user_input: str, clean_trimmed_text: str):
    """기사 구조 생성 프롬프트"""
    return f"""
    🧾 다음은 기사나 리뷰 콘텐츠로 활용될 수 있는 초안 정보 또는 요약 내용이야:

    {clean_trimmed_text}...

    ---

    🎯 사용자 입력 주제: {user_input}

    ---

    이 내용을 먼저 분석해서, 전체 글의 구조와 감정 흐름 또는 정보 흐름을 파악한 뒤, 다음을 수행해줘:

    ---

    🧠 수행할 작업:

    ⚠️ **중요 주의사항**: 
    - 제목이나 내용에 키워드가 중복되지 않도록 주의해주세요
    - 자연스럽고 매끄러운 문장으로 작성해주세요

    1️⃣ `section_titles` 구성  
    문단 제목은 **"1편: [내용]", "2편: [내용]", "3편: [내용]"** 형식으로 구성해주세요.
    
    첫 번째 문단(1편)에는 아래 정보가 꼭 들어가야 합니다:
    - 장르 (드라마, 예능, 애니메이션, 영화 등)
    - 정식 제목 및 시즌/회차 (예: 나는 솔로 17기 4회)
    - 방송사/플랫폼 (예: SBS, ENA, Netflix 등)
    - 주요 인물 또는 시청 포인트 간단 요약
    - 게임/대회 정보 (해당 시, 꼭 포함)
    - 이미지 없는 포스팅임을 자연스럽게 알리는 문장
      (예: "이번 리뷰는 오직 글로만, 상상으로 장면을 떠올려봅니다." 등)

    이후 문단들(2편~6편)은:
    - **소설처럼 자연스럽게 이어지는 이야기**로 구성해주세요
    - 각 편이 이전 편의 내용을 받아서 다음 편으로 자연스럽게 연결
    - 마치 한 편의 소설을 읽는 것처럼, 독자가 계속해서 다음 편을 읽고 싶게 만드는 흐름
    - 각 편의 마지막 부분에서 다음 편으로 이어질 수 있는 호기심을 자극하는 요소 포함
    - 총 4~6개의 편으로 구성 (1편 + 3~5개의 추가 편)

    예시 형식:
    - "1편: [주제 소개 및 기본 정보]"
    - "2편: [1편에서 이어지는 핵심 내용 전개]"
    - "3편: [2편의 내용을 바탕으로 한 세부 분석]"
    - "4편: [3편의 분석을 토대로 한 결론 및 마무리]"

    2️⃣ `final_title` 생성  
    - 위 흐름에 어울리는 **완성도 높은 기사 또는 리뷰 제목**을 만들어줘  
    - 자극적인 표현은 피하고, **정보 흐름을 요약하며 감정이 묻어나는 문장형 제목**이면 좋아  
    - 독자가 어떤 내용을 읽게 될지 **예측 가능하면서도 매끄럽게 이끄는 제목**
    - 제목에는 연관 키워드 및 태그를 2 ~ 3개 항상 포함 시켜줘
    - **중요**: 제목에 키워드가 중복되지 않도록 주의해주세요

    ---

    📦 최종 응답은 반드시 아래 JSON 형식으로 반환해:

    {{
    "section_titles": [
      "1편: ALGS Group B, 숨막히는 서바이벌의 서막",
      "2편: 서막을 넘어선 게임의 룰, 왜 마지막에 데스매치처럼 되는가",
      "3편: 데스매치 속에서 빛난 FUSN, 순수 한국 대표팀의 존재감",
      "4편: FUSN의 활약 뒤에 숨겨진 CR 속 리젝트 멤버들, 국적을 넘은 전장의 동료들",
      "5편: 동료들의 응원 속에서 일어난 한 틱의 기적과 한국 팬들의 폭발적 반응",
      "6편: 리젝트는 탈락했지만, 그들이 남긴 이야기는 이어진다"
    ],
    "final_title": "나는 솔로 17기 4회, 정적 속에서 피어난 감정의 진폭"
    }}
    """


def build_paragraph_prompt(section_title, final_title, user_input, clean_trimmed_text, section_titles=None, previous_content="", search_engine="bing"):
    """문단 생성 프롬프트 (이전 내용 포함, 중복 방지 기능 추가)"""
    # 검색 키워드 생성 (섹션 제목과 사용자 입력을 조합)
    search_keywords = f"{section_title} {user_input} {clean_trimmed_text}".strip()
    # 특수문자 제거 및 공백 정리
    search_keywords = re.sub(r'[^\w\s가-힣]', ' ', search_keywords)
    search_keywords = ' '.join(search_keywords.split())
    
    # 검색 링크 생성
    try:
        from utils import generate_search_link
        search_url = generate_search_link(search_keywords, search_engine)
        search_engine_name = search_engine.capitalize()
    except ImportError:
        # utils 모듈을 찾을 수 없는 경우 기본 Bing 링크 사용
        from urllib.parse import quote
        if search_engine.lower() == "naver":
            search_url = f"https://search.naver.com/search.naver?query={quote(search_keywords)}"
            search_engine_name = "Naver"
        elif search_engine.lower() == "google":
            search_url = f"https://www.google.com/search?q={quote(search_keywords)}"
            search_engine_name = "Google"
        else:
            search_url = f"https://www.bing.com/search?q={quote(search_keywords)}&sendquery=1&FORM=SCCODX&rh=B0D80A4F&ref=rafsrchae"
            search_engine_name = "Bing"
    
    # 이전 내용이 있는 경우와 없는 경우를 구분하여 프롬프트 생성
    if previous_content and previous_content.strip():
        context_instruction = f"""
    📚 현재까지 작성된 내용:
    {previous_content[:1000]}{'...' if len(previous_content) > 1000 else ''}
    
    📝 이전 내용을 바탕으로 **"{section_title}"** 부분을 자연스럽게 이어서 작성해주세요.
    """
    else:
        context_instruction = f"""
    📝 **"{section_title}"** 부분을 처음부터 작성해주세요.
    """

    return f"""
    '{final_title}'이라는 블로그 포스트에서,  
    **"{section_title}"** 부분을 작성해주세요.{context_instruction}

    📚 전체 문단 주제 목록: "{section_titles if section_titles else '정보 없음'}"  
    📝 현재 작성 대상 단락: "{section_title}"

    📌 글 작성에 참고할 기반 정보:
    1. 사용자 입력 내용: {user_input}
    2. 요약 키워드: {clean_trimmed_text}
    3. 검색 키워드: {search_keywords}

    📐 작성 가이드라인:
    - 문단은 `<p>` 태그로 감싸고, `{section_title}`은 `<h2>` 태그로 별도로 출력합니다.
    - **경어체**와 **친근한 말투**를 사용하여 **500자 이내**로 작성합니다.
    - **필수 키워드**는 문맥에 맞게 1~2회 자연스럽게 포함해주세요.
    - **중요 단어나 추천 키워드에 하이퍼링크**를 삽입하거나, 문장 흐름에 맞춰  
      **공식 검색 플랫폼({search_engine_name}, Naver, Google, YouTube)** 링크를 자연스럽게 걸어주세요.
    - 검색 엔진: **{search_engine_name}**을 기본으로 사용하되, 필요시 다른 검색 엔진 링크도 함께 사용할 수 있습니다. 
    
    🔗 자연스러운 연결 지침:
    - 이전 내용이 있다면, 그 내용을 자연스럽게 받아서 현재 섹션으로 연결해주세요.
    - "앞서 말씀드린", "이어서", "그런데", "한편" 등의 연결어를 활용하여 매끄럽게 이어주세요.
    - 이전 섹션에서 언급된 키워드나 개념을 현재 섹션에서 자연스럽게 발전시켜주세요.
    - 독자가 이전 내용을 읽었다고 가정하고, 중복 설명은 최소화하되 필요한 맥락은 유지해주세요.

    - 문장 사이에는 `<br>` 태그를 적절히 넣어 가독성을 높여주세요.

    🔗 링크 예시 (구체적인 검색어 사용):
    ```html
    <p>
    이번 오징어 게임 시즌3는 전 세계적으로 큰 화제를 모으고 있어요.<br>
    관련 정보는 <a href="{search_url}" target="_blank">{search_engine_name} 검색</a>에서 바로 확인해보세요.<br>
    더 자세한 정보는 <a href="https://www.youtube.com/results?search_query={search_keywords}" target="_blank">YouTube</a>에서도 찾아볼 수 있어요!
    </p>
    ```

    🔍 구체적인 검색 링크 생성 방법:
    - 섹션 제목: "{section_title}"
    - 사용자 입력: {user_input}
    - 검색 키워드: {search_keywords}
    - 선택된 검색 엔진: {search_engine_name}
    - 실제 검색 URL: {search_url}

    ❗ 허용되는 링크 출처:
    - YouTube (https://www.youtube.com/results?search_query=검색어)
    - Naver (https://search.naver.com/search.naver?query=검색어)
    - Google (https://www.google.com/search?q=검색어)
    - Bing (https://www.bing.com/search?q=검색어&sendquery=1&FORM=SCCODX&rh=B0D80A4F&ref=rafsrchae)

    ⛔ 아래 출처는 절대 금지:
    - 개인 블로그, 광고성 페이지, 비공식 출처 등

    📦 최종 출력은 아래 JSON 형식으로 반환:
    {{
      "section_title": "{section_title}",
      "content": "<p>문단 내용...</p>"
    }}
    """


def build_blog_post_prompt(user_input: str, clean_trimmed_text: str):
    """블로그 포스트 생성 프롬프트"""
    return f"""
    다음은 대한민국 실시간 트렌드 데이터입니다:

    {clean_trimmed_text}

    이 데이터를 바탕으로 아래 형식에 따라 감성 뉴스 기사(교육·수능 특화)를 작성해줘. 
    전체 문체는 한강 작가 스타일로, 감성적이되 절제된 톤을 유지해.

    [STEP 1] 기사 제목 생성
    - 실존하는 최근 이슈를 기반으로 작성
    - '수능', '문제집', '안 풀리는 문제', '공부법', '기출 분석' 등의 키워드 포함
    - 검색 유입률이 높을 만한 제목 5개 생성
    - 그중 최종 선택 제목 1개도 명시

    [STEP 2] 기사 작성 지침
    - 구조는 다음과 같아:
      1. 헤드라인
      2. 리드문 (시간, 장소, 인물 포함 도입부)
      3. 본문 (정보 → 통계 → 분석)
      4. 결론 (여운과 전망)
      5. 유튜브 검색 키워드 1개
      6. 감성 이모지 구분자 포함 마무리 멘트

    - 기사 분량: 최소 3500자 이상 (가능하면 4000자까지 확대)
    - HTML 형식(`<h2>`, `<p>`, `<br>`, `<blockquote>`, `<ul>` 등)을 사용해서 작성
    - 사용 가능한 감성 구분자: ⋆｡°✩, 𓂃◌𓈒𓏸, ❋, ✦, ✸, ✷, ✿, ⟢
    - 금지 이모지: 📌, 🎬, ✅, 😊 등 정보용 아이콘 금지

    ※ 링크를 삽입할때는 URL 주소도 써주세요.
    ※ 이미지를 추가해주세요.
    ※ 이미지를 추가할 때는 <img src='이미지주소'> 형식으로 삽입해주세요.

    아래 JSON 형식으로만 응답해줘:
    {{
      "titles": ["제목 후보1", "제목 후보2", ..., "제목 후보5"],
      "final_title": "최종 선택 제목",
      "content": "<HTML로 작성된 기사 본문>",
      "keyword": "본문의 핵심 키워드 최소 2단어",
      "summary": "한 줄 요약",
      "youtube_keyword": "관련 유튜브 검색어"
    }}
    """


def extract_json(text):
    """텍스트에서 JSON 추출"""
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    match = re.search(json_pattern, text)
    return match.group(0) if match else None


def generate_filename():
    """타임스탬프 기반 파일명 생성"""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{timestamp}_huggingface_demo_img.png"


def clean_json_string(raw_text):
    """JSON 문자열 정리"""
    # dict일 경우 문자열로 직렬화
    if isinstance(raw_text, dict):
        return json.dumps(raw_text, ensure_ascii=False)
    
    # 문자열에서 JSON 부분만 추출
    def escape_html_quotes(match):
        return match.group(0).replace('"', '\\"')
    
    # HTML 태그 내의 따옴표 이스케이프
    cleaned = re.sub(r'<[^>]*>', escape_html_quotes, raw_text)
    
    # JSON 부분 추출
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    match = re.search(json_pattern, cleaned)
    
    if match:
        return match.group(0)
    else:
        return raw_text


def fix_missing_content_key(json_like_text, content_text):
    """JSON에 content 키가 없으면 추가"""
    # JSON에서 content 키가 있는지 확인
    if '"content"' not in json_like_text:
        # content 키를 추가
        json_like_text = json_like_text.rstrip('}') + f', "content": "{content_text}"' + '}'
    
    return json_like_text, content_text


def generate_gpt_prompt_from_html(html_content):
    """HTML 내용에서 텍스트 추출하여 GPT 프롬프트 생성"""
    # HTML 태그 제거
    clean_text = re.sub(r'<[^>]+>', '', html_content)
    
    # 연속된 공백 제거
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    return clean_text


if __name__ == "__main__":
    print("🚀 prompt_utils.py 테스트 시작")
    print("=" * 50)
    
    # sanitize_prompt 테스트
    print("🧪 sanitize_prompt 함수 테스트")
    test_text = "테스트 텍스트" + '\x00' + "널문자 포함"
    result = sanitize_prompt(test_text)
    print(f"입력: {test_text}")
    print(f"결과: {result}")
    print("✅ sanitize_prompt 테스트 완료\n")
    
    # safe_json_parse 테스트
    print("🧪 safe_json_parse 함수 테스트")
    test_cases = [
        ('{"key": "value"}', "정상 JSON"),
        ('```json\n{"key": "value"}\n```', "마크다운 JSON"),
        ('<h2>제목</h2><p>내용</p>', "HTML 태그"),
    ]
    
    for test_input, description in test_cases:
        try:
            result = safe_json_parse(test_input, f"테스트: {description}")
            print(f"✅ {description}: {result}")
        except Exception as e:
            print(f"❌ {description}: {e}")
    print("✅ safe_json_parse 테스트 완료\n")
    
    # build_article_from_existing_structure 테스트
    print("🧪 build_article_from_existing_structure 함수 테스트")
    test_input = "나는 솔로 17기"
    test_text = "나는 솔로 17기 4회 방송 내용 요약..."
    result = build_article_from_existing_structure(test_input, test_text)
    print(f"입력 주제: {test_input}")
    print(f"입력 텍스트: {test_text}")
    print(f"생성된 프롬프트 길이: {len(result)} 문자")
    print("✅ build_article_from_existing_structure 테스트 완료\n")
    
    # extract_json 테스트
    print("🧪 extract_json 함수 테스트")
    test_cases = [
        ('여기 JSON이 있어요: {"key": "value"} 끝', '{"key": "value"}'),
        ('JSON 없음', None),
        ('{"nested": {"inner": "value"}}', '{"nested": {"inner": "value"}}'),
    ]
    
    for test_input, expected in test_cases:
        result = extract_json(test_input)
        print(f"입력: {test_input}")
        print(f"결과: {result}")
        print(f"예상: {expected}")
        print("---")
    print("✅ extract_json 테스트 완료\n")
    
    # generate_filename 테스트
    print("🧪 generate_filename 함수 테스트")
    result = generate_filename()
    print(f"생성된 파일명: {result}")
    print("✅ generate_filename 테스트 완료\n")
    
    # generate_gpt_prompt_from_html 테스트
    print("🧪 generate_gpt_prompt_from_html 함수 테스트")
    test_html = "<h2>제목</h2><p>테스트 내용입니다.</p>"
    result = generate_gpt_prompt_from_html(test_html)
    print(f"입력 HTML: {test_html}")
    print(f"결과: {result}")
    print("✅ generate_gpt_prompt_from_html 테스트 완료\n")
    
    print("=" * 50)
    print("🎉 모든 테스트 완료!")