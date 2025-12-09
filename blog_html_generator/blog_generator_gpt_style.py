"""
블로그 생성기 - gpt_chat_interface.py와 완전히 동일한 방식
gpt_chat_interface.py의 블로그 글 생성 로직을 그대로 사용
"""

import sys
import os
import json
import re
import json5
from urllib.parse import quote
from openai import OpenAI

# OpenAI API 키 설정 (환경 변수 또는 설정 파일에서 로드)
import os
api_key = os.getenv("OPENAI_API_KEY", "")
if not api_key:
    # 설정 파일에서 로드 시도
    try:
        import json
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "openai_config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                api_key = config.get("api_key", "")
    except:
        pass
client = OpenAI(api_key=api_key) if api_key else None


class BlogGeneratorGPTStyle:
    """gpt_chat_interface.py와 완전히 동일한 블로그 생성 방식"""
    
    def __init__(self, config=None):
        """초기화"""
        self.config = config or {
            "chat_model": "gpt-4o-mini",
            "image_source": "bing"
        }
        self.collected_web_data = ""
        self.collected_urls = []
        self._current_coupang_product = None
    
    def call_chat_with_fallback(self, messages, primary_model="gpt-4o-mini", temperature=0.3, max_tokens=500):
        """모델/파라미터 호환성 처리"""
        model_candidates = [primary_model]
        token_param_candidates = [None, "max_tokens", "max_completion_tokens"]
        temperature_modes = [
            ("given", temperature),
            ("one", 1),
            ("omit", None),
        ]
        for model_name in model_candidates:
            for token_param in token_param_candidates:
                for temp_mode, temp_value in temperature_modes:
                    try:
                        params = {
                            "model": model_name,
                            "messages": messages,
                        }
                        if temp_mode != "omit":
                            params["temperature"] = temp_value
                        if token_param is not None and max_tokens is not None:
                            params[token_param] = max_tokens
                        return client.chat.completions.create(**params)
                    except Exception as e:
                        err = str(e)
                        if (
                            "Unsupported parameter" in err
                            and ("max_tokens" in err or "max_completion_tokens" in err)
                        ):
                            print(f"⚠️ 모델 '{model_name}'에서 '{token_param}' 미지원 → 대체 토큰 파라미터 시도")
                            break
                        if (
                            "Unsupported value" in err and "temperature" in err
                        ):
                            print(f"⚠️ 모델 '{model_name}'에서 temperature 값 미지원 → 대체 temperature 모드 시도")
                            continue
                        if (
                            "model_not_found" in err
                            or "does not have access" in err
                            or "403" in err
                        ):
                            print(f"⚠️ 모델 '{model_name}' 사용 불가, 다음 후보로 폴백: {err}")
                            break
                        raise
        raise Exception("사용 가능한 모델이 없습니다. 허용 모델 및 권한을 확인하세요.")
    
    def gpt(self, user_content: str, system_content: str = None, temperature: float = 0.3,
            max_tokens: int = 500, primary_model: str = None) -> str:
        """단일 GPT 호출 함수: system/user를 받아 텍스트 응답(content)만 반환"""
        messages = []
        if system_content:
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": user_content})
        if not primary_model:
            primary_model = self.config.get("chat_model", "gpt-4o-mini")
        resp = self.call_chat_with_fallback(
            messages=messages,
            primary_model=primary_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    
    def extract_json_from_text(self, text):
        """텍스트에서 JSON 블록을 추출하는 함수"""
        try:
            print(f"🔍 JSON 추출 시작 - 텍스트 길이: {len(text)}")
            
            # 1. 코드 블록에서 JSON 추출 시도
            code_block_patterns = [
                r"```json\s*(\{[\s\S]*?\})\s*```",
                r"```\s*(\{[\s\S]*?\})\s*```",
                r"`(\{[\s\S]*?\})`"
            ]
            
            for pattern in code_block_patterns:
                match = re.search(pattern, text)
                if match:
                    json_str = match.group(1)
                    try:
                        json.loads(json_str)
                        print(f"✅ 코드 블록에서 JSON 추출 성공")
                        return json_str
                    except:
                        continue
            
            # 2. 중괄호로 둘러싸인 JSON 객체 추출
            json_patterns = [
                r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
                r"\{[^}]*\}",
                r"\{[\s\S]*?\}"
            ]
            
            for pattern in json_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    try:
                        json.loads(match)
                        print(f"✅ 정규식 패턴에서 JSON 추출 성공")
                        return match
                    except:
                        continue
            
            # 3. 텍스트 정리 후 재시도
            cleaned_text = text
            cleaned_text = re.sub(r'[^\x00-\x7F]+', '', cleaned_text)
            cleaned_text = re.sub(r"^\s*[*\-+]\s*", "", cleaned_text, flags=re.MULTILINE)
            cleaned_text = re.sub(r"^\s*#+\s*", "", cleaned_text, flags=re.MULTILINE)
            cleaned_text = re.sub(r'\n\s*\n', '\n', cleaned_text)
            
            for pattern in json_patterns:
                matches = re.findall(pattern, cleaned_text)
                for match in matches:
                    try:
                        json.loads(match)
                        print(f"✅ 정리된 텍스트에서 JSON 추출 성공")
                        return match
                    except:
                        continue
            
            # 4. 마지막 시도: 키워드 기반
            if '"final_title"' in text or '"section_titles"' in text:
                start_idx = max(0, text.find('{'))
                end_idx = text.rfind('}') + 1
                if start_idx < end_idx:
                    potential_json = text[start_idx:end_idx]
                    try:
                        json.loads(potential_json)
                        print(f"✅ 키워드 기반 JSON 추출 성공")
                        return potential_json
                    except:
                        pass
            
            print(f"❌ JSON 추출 실패 - 모든 방법 시도 완료")
            return None
            
        except Exception as e:
            print(f"JSON 추출 중 오류: {e}")
            return None
    
    def extract_section_titles_from_text(self, text):
        """텍스트에서 섹션 제목을 추출하는 대체 방법"""
        try:
            print(f"🔍 텍스트에서 섹션 제목 추출 시도...")
            
            patterns = [
                r'(\d+\.\s*[^\n]+)',
                r'(\d+\)\s*[^\n]+)',
                r'([A-Z][^.\n]+\.)',
                r'([가-힣][^.\n]+에\s+대해)',
                r'([가-힣][^.\n]+의\s+특징)',
                r'([가-힣][^.\n]+방법)',
            ]
            
            titles = []
            for pattern in patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    title = match.strip()
                    if len(title) > 3 and len(title) < 50:
                        titles.append(title)
            
            unique_titles = []
            seen_titles = set()
            for title in titles:
                normalized = title.strip().lower()
                if normalized and normalized not in seen_titles:
                    seen_titles.add(normalized)
                    unique_titles.append(title)
            
            if unique_titles:
                result = unique_titles[:5]
                print(f"✅ 섹션 제목 추출 성공: {result}")
                return result
            
            print(f"⚠️ 패턴 매칭 실패, 기본 섹션 제목 생성")
            default_titles = [
                "주요 특징",
                "핵심 내용", 
                "중요한 포인트",
                "추가 정보",
                "결론"
            ]
            return default_titles
            
        except Exception as e:
            print(f"섹션 제목 추출 실패: {e}")
            return None
    
    def parse_article_structure(self, response_text, keyword=""):
        """GPT 응답에서 글 구조를 파싱하는 함수"""
        try:
            print(f"🔍 글 구조 파싱 시작 - 응답 길이: {len(response_text)}")
            
            json_block = self.extract_json_from_text(response_text)
            if not json_block:
                print(f"❌ JSON 블록을 찾을 수 없습니다")
                print(f"📄 원본 응답 미리보기: {response_text[:300]}...")
                
                print(f"🔄 대체 방법으로 섹션 제목 추출 시도...")
                fallback_titles = self.extract_section_titles_from_text(response_text)
                if fallback_titles:
                    print(f"✅ 대체 방법으로 섹션 제목 추출 성공: {fallback_titles}")
                    generated_title = f"{keyword} - 상세 분석 및 가이드"
                    return fallback_titles, generated_title
                else:
                    raise ValueError("JSON 블록을 찾을 수 없습니다")
            
            parsed = None
            
            try:
                parsed = json5.loads(json_block)
                print(f"✅ json5로 파싱 성공")
            except Exception as e:
                print(f"⚠️ json5 파싱 실패: {e}")
            
            if not parsed:
                try:
                    parsed = json.loads(json_block)
                    print(f"✅ 표준 json으로 파싱 성공")
                except Exception as e:
                    print(f"⚠️ 표준 json 파싱 실패: {e}")
            
            if not parsed:
                try:
                    cleaned_json = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_block)
                    cleaned_json = re.sub(r'[^\x20-\x7e]', '', cleaned_json)
                    parsed = json.loads(cleaned_json)
                    print(f"✅ 정리된 json으로 파싱 성공")
                except Exception as e:
                    print(f"⚠️ 정리된 json 파싱 실패: {e}")
            
            if not parsed:
                try:
                    cleaned_json = re.sub(r'[^\x00-\x7F]+', '', json_block)
                    cleaned_json = re.sub(r'[^\x20-\x7e]', '', cleaned_json)
                    parsed = json.loads(cleaned_json)
                    print(f"✅ 이모지 제거 후 json 파싱 성공")
                except Exception as e:
                    print(f"⚠️ 이모지 제거 후 json 파싱 실패: {e}")
            
            if not parsed:
                print(f"❌ 모든 JSON 파싱 방법 실패")
                print(f"📄 JSON 블록: {json_block}")
                raise ValueError("JSON 파싱에 실패했습니다")
            
            section_titles_raw = parsed.get("section_titles", [])
            final_title = parsed.get("final_title", "❌ 없음")
            
            section_titles_temp = []
            for title in section_titles_raw:
                if isinstance(title, str):
                    section_titles_temp.append(title)
                else:
                    print(f"⚠️ 잘못된 섹션 제목 타입: {type(title)}, 값: {title}")
                    section_titles_temp.append(str(title))
            
            section_titles = []
            seen_titles = set()
            for title in section_titles_temp:
                normalized = title.strip().lower()
                if normalized and normalized not in seen_titles:
                    seen_titles.add(normalized)
                    section_titles.append(title)
                else:
                    print(f"⚠️ 중복된 섹션 제목 제거: {title}")
            
            if not section_titles:
                print(f"⚠️ 섹션 제목이 없습니다. 대체 방법 시도...")
                fallback_titles = self.extract_section_titles_from_text(response_text)
                if fallback_titles:
                    print(f"✅ 대체 방법으로 섹션 제목 추출 성공: {fallback_titles}")
                    if final_title == "❌ 없음" or final_title == "자동 생성된 제목":
                        final_title = f"{keyword} - 종합 분석 리포트"
                    return fallback_titles, final_title
                else:
                    raise ValueError("섹션 제목이 없습니다")
            
            if len(section_titles) < len(section_titles_raw):
                print(f"⚠️ 중복 제거로 인해 섹션 제목이 {len(section_titles)}개로 줄어듦 (원본: {len(section_titles_raw)}개)")
            
            print("✅ JSON 파싱 성공!")
            print("📌 section_titles:", section_titles)
            print("📌 final_title:", final_title)
            
            return section_titles, final_title
            
        except Exception as e:
            print(f"❌ JSON 파싱 오류: {e}")
            print(f"📄 원본 응답: {response_text[:500]}...")
            raise Exception(f"글 구조 파싱 실패: {e}")
    
    def create_fallback_section_data(self, section_title, response_text):
        """JSON 파싱 실패 시 대체 섹션 데이터 생성"""
        try:
            content = response_text.strip()
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            content = re.sub(r'^\s*[*\-+]\s*', '', content, flags=re.MULTILINE)
            content = re.sub(r'^\s*#+\s*', '', content, flags=re.MULTILINE)
            
            if len(content) > 50:
                detailed_image_prompt = f"{section_title} 관련 상세한 일러스트레이션, 고화질, 상세한 묘사"
                return {
                    "section_title": section_title,
                    "content": f"<p>{content}</p>",
                    "image_prompt": detailed_image_prompt
                }
            
            return None
            
        except Exception as e:
            print(f"대체 데이터 생성 실패: {e}")
            return None
    
    def generate_optimal_search_keywords_for_main(self, keyword):
        """메인 검색어 생성을 위한 GPT 함수"""
        try:
            print(f"🤖 GPT로 메인 검색어 생성 중: {keyword}")
            
            prompt = f"""
다음 주제에 대한 최적의 웹 검색어를 생성해주세요.

📝 주제: {keyword}

📋 검색어 생성 조건:
- 해당 주제를 이해하고 검색어를 생성해주세요. bing.com 에서 사용할 검색어입니다.
생성된 검색어만 출력해주세요 (설명 없이):
"""
            
            response = self.call_chat_with_fallback(
                messages=[
                    {"role": "system", "content": "웹 검색에 최적화된 검색어를 생성하는 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                primary_model=self.config.get("chat_model", "gpt-4o-mini"),
                temperature=0.3,
                max_tokens=50
            )
            
            generated_keywords = response.choices[0].message.content.strip()
            generated_keywords = re.sub(r'[^\w\s가-힣]', ' ', generated_keywords)
            generated_keywords = ' '.join(generated_keywords.split())
            
            if len(generated_keywords) > 50:
                generated_keywords = ' '.join(generated_keywords.split()[:3])
            
            if not generated_keywords or len(generated_keywords.strip()) < 2:
                print(f"⚠️ GPT 메인 검색어 생성 실패, 기본 검색어 사용")
                generated_keywords = keyword.strip()
                generated_keywords = re.sub(r'[^\w\s가-힣]', ' ', generated_keywords)
                generated_keywords = ' '.join(generated_keywords.split()[:3])
            
            print(f"✅ 생성된 검색어: {generated_keywords}")
            return generated_keywords
            
        except Exception as e:
            print(f"❌ 메인 검색어 생성 실패: {e}")
            fallback_keywords = keyword.strip()
            fallback_keywords = re.sub(r'[^\w\s가-힣]', ' ', fallback_keywords)
            fallback_keywords = ' '.join(fallback_keywords.split()[:3])
            return fallback_keywords
    
    def organize_collected_data_with_gpt(self, keyword, collected_data):
        """수집된 데이터를 GPT로 정리하는 함수"""
        try:
            print(f"🤖 수집된 데이터 정리 중: {len(collected_data)}자")
            
            prompt = f"""
다음은 웹에서 수집된 원본 데이터입니다. 이 데이터를 사용자 요청 사항 중심으로 정리해주세요.

🎯 **사용자 요청 사항**: {keyword}

📋 **정리 조건**:
- 사용자 요청 사항을 중심으로 관련성 높은 정보만 선별
- 중복 내용 제거
- 핵심 사실과 정보 위주로 정리
- 2000자 이내로 간결하게 요약
- 문단별로 구분하여 정리

📄 **수집된 원본 데이터**:
{collected_data[:8000]}

정리된 데이터만 출력해주세요 (설명 없이):
"""
            
            response = self.call_chat_with_fallback(
                messages=[
                    {"role": "system", "content": "웹 데이터를 사용자 요청 중심으로 정리하는 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                primary_model=self.config.get("chat_model", "gpt-4o-mini"),
                temperature=0.3,
                max_tokens=2000
            )
            
            organized_data = response.choices[0].message.content.strip()
            print(f"✅ 데이터 정리 완료: {len(organized_data)}자")
            return organized_data
            
        except Exception as e:
            print(f"❌ 데이터 정리 실패: {e}")
            return collected_data[:2000] if len(collected_data) > 2000 else collected_data
    
    def collect_web_data_for_section(self, section_title, keyword, clean_trimmed_text):
        """섹션별 데이터 제공 (이미 정리된 데이터 사용)"""
        try:
            print(f"📝 섹션 데이터 준비 중: {section_title}")
            
            organized_data = getattr(self, 'collected_web_data', '')
            
            if organized_data:
                result = {
                    "search_keywords": keyword,
                    "web_contents": [organized_data[:1500]],
                    "urls": getattr(self, 'collected_urls', [f"https://www.bing.com/search?q={keyword}"]),
                    "titles": [f"{section_title} 관련 정보"]
                }
                print(f"✅ 섹션 데이터 준비 완료: {len(organized_data)}자")
                return result
            else:
                return {
                    "search_keywords": keyword,
                    "web_contents": [f"{section_title}에 대한 정보를 찾아보세요."],
                    "urls": getattr(self, 'collected_urls', [f"https://www.bing.com/search?q={keyword}"]),
                    "titles": [f"{section_title} 검색 결과"]
                }
            
        except Exception as e:
            print(f"❌ 섹션 데이터 준비 실패: {e}")
            return {
                "search_keywords": keyword,
                "web_contents": [f"{section_title}에 대한 정보를 찾아보세요."],
                "urls": getattr(self, 'collected_urls', [f"https://www.bing.com/search?q={keyword}"]),
                "titles": [f"{section_title} 검색 결과"]
            }
    
    def build_section_prompt_with_web_data(self, section_title, final_title, keyword, clean_trimmed_text, collected_data, previous_content=""):
        """웹 수집 데이터를 포함한 섹션 프롬프트 생성"""
        
        user_request_section = f"""
🎯 **사용자 요청 사항 (가장 중요)**:
사용자가 요청한 주제: "{keyword}"

이 요청 사항을 반드시 중심으로 하여 섹션을 작성해주세요.
사용자가 원하는 내용과 방향성을 정확히 파악하여 작성하세요.

📝 **기존 작성된 내용 (참고용)**:
{previous_content}

위 기존 내용을 참고하여 중복되지 않는 새로운 관점과 정보로 전개해주세요.
"""
        
        context_instruction = ""
        if previous_content and previous_content.strip():
            context_instruction = f"""
이전 내용: {previous_content[:500]}{'...' if len(previous_content) > 500 else ''}

위 내용을 바탕으로 자연스럽게 이어서 작성해주세요.
"""
        
        web_data_section = ""
        if collected_data["web_contents"]:
            web_data_section = "참고할 웹 정보:\n"
            for i, content in enumerate(collected_data["web_contents"][:2], 1):
                limited_content = content[:100] + "..." if len(content) > 100 else content
                web_data_section += f"{i}. {limited_content}\n"
        
        url_section = ""
        if collected_data.get("urls"):
            url_section = "핵심 단어 링크 (본문에서 자동 적용):\n"
            
            core_terms = []
            title_words = section_title.split()
            for word in title_words:
                if len(word) >= 2:
                    core_terms.append(word)
            
            keyword_words = keyword.split()
            for word in keyword_words:
                if len(word) >= 2 and word not in core_terms:
                    core_terms.append(word)
            
            for i, term in enumerate(core_terms[:5], 1):
                section_keywords = []
                for word in section_title.split():
                    if len(word) >= 2 and word != term:
                        section_keywords.append(word)
                
                keyword_parts = []
                for word in keyword.split():
                    if len(word) >= 2 and word != term:
                        keyword_parts.append(word)
                
                search_components = [term]
                search_components.extend(section_keywords[:2])
                search_components.extend(keyword_parts[:2])
                
                detailed_search = " ".join(search_components)
                
                if len(detailed_search) < 10:
                    detailed_search = f"{term} {keyword} {section_title}"
                
                search_query = quote(detailed_search)
                # 설정에서 검색 엔진 가져오기
                search_engine = self.config.get("search_engine", "bing").lower()
                try:
                    import sys
                    import os
                    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    if parent_dir not in sys.path:
                        sys.path.insert(0, parent_dir)
                    from utils import generate_search_link
                    search_url = generate_search_link(detailed_search, search_engine)
                except ImportError:
                    # utils 모듈을 찾을 수 없는 경우 직접 생성
                    if search_engine == "naver":
                        search_url = f"https://search.naver.com/search.naver?query={search_query}"
                    elif search_engine == "google":
                        search_url = f"https://www.google.com/search?q={search_query}"
                    else:  # bing (기본값)
                        search_url = f"https://www.bing.com/search?q={search_query}&sendquery=1&FORM=SCCODX&rh=B0D80A4F&ref=rafsrchae"
                url_section += f"{i}. {term} → <a href=\"{search_url}\" target=\"_blank\">{term}</a> (검색어: {detailed_search}, 엔진: {search_engine})\n"

        return f"""
{user_request_section}

'{final_title}' 블로그 포스트의 "{section_title}" 섹션을 작성해주세요.

{context_instruction}

주제: {keyword}
키워드: {clean_trimmed_text}
검색어: {collected_data["search_keywords"]}

{web_data_section}

{url_section}

작성 요구사항:
- 최소 300자 이상 (권장 300~500자)
- 경어체 사용
- 자연스럽고 읽기 쉬운 문체
- 제목은 포함하지 말고 내용만 작성
- HTML 태그 사용: <p>내용</p>, <br>줄바꿈
- **핵심 단어 링크가 있으면 본문에서 해당 단어가 나올 때마다 <a href="bing.com?search=해당 주제를 이해하고 핵심 주제 + 검색어를 써주세요">단어</a> 형태로 자연스럽게 포함**
- **사용자 요청 사항을 반드시 반영하여 작성**

📋 **자유로운 문단 작성 및 중복 방지**:
기존에 작성된 내용을 참고하여 자유롭게 문단을 작성해주세요:

1. **이전 내용 분석**: 
   - 앞서 작성된 모든 내용을 확인하여 중복되는 정보 파악
   - 기존에 언급된 핵심 정보들을 정리

2. **자유로운 전개**:
   - 문단의 주제나 방향은 자유롭게 설정
   - 기존 내용을 바탕으로 새로운 관점이나 정보 추가
   - 이전에 언급하지 않은 새로운 분석, 예측, 관점 제공

3. **자연스러운 연결**:
   - 기존 내용과 자연스럽게 연결되도록 작성
   - "앞서 언급한", "이러한 배경에서", "이에 더해" 등의 연결어 활용
   - 기존 정보를 참고하되 새로운 내용으로 전개

⚠️ **중요: 반드시 JSON 형식으로만 응답하세요!**

다음 JSON 형식으로 정확히 응답해주세요:
```json
{{
    "section_title": "{section_title}",
    "content": "HTML 형식의 섹션 내용 (제목 제외)",
    "image_prompt": "이 섹션을 위한 상세한 이미지 프롬프트 (한국어, 100자 이상 권장)"
}}
```

**JSON 응답 규칙:**
1. 반드시 ```json으로 시작하고 ```로 끝내세요
2. JSON 객체는 정확한 형식을 지켜주세요
3. 문자열 값에는 반드시 큰따옴표를 사용하세요
4. 다른 설명이나 텍스트는 포함하지 마세요
5. JSON 형식만 응답하세요

**이미지 프롬프트 작성 가이드:**
- 섹션 내용을 바탕으로 구체적이고 상세한 이미지 프롬프트 작성
- 한국어로 작성
- 최소 100자 이상 권장
- 섹션의 핵심 내용을 시각적으로 표현할 수 있는 상세한 설명 포함
"""
    
    def generate_section_content(self, section_title, final_title, keyword, clean_trimmed_text, i, previous_sections_content=""):
        """개별 섹션의 내용을 생성하는 함수 (웹 수집 + GPT 생성)"""
        print(f"📝 [{i+1}] 섹션 '{section_title}' 웹 수집 및 내용 생성 중...")
        
        try:
            collected_data = self.collect_web_data_for_section(section_title, keyword, clean_trimmed_text)
            section_prompt = self.build_section_prompt_with_web_data(
                section_title, final_title, keyword, clean_trimmed_text, 
                collected_data, previous_sections_content
            )
            
            response_text = self.gpt(
                user_content=section_prompt,
                temperature=0.3,
                max_tokens=700,
            )
            json_block = self.extract_json_from_text(response_text)
            
            if not json_block:
                print(f"❌ JSON 블록을 찾을 수 없습니다 - 재시도 시도")
                retry_prompt = section_prompt + f"\n\n중요: 반드시 아래 JSON 형식으로만 응답하고, 본문(content)은 최소 300자 이상으로 작성하세요. 설명 금지.\n```json\n{{\n  \"section_title\": \"{section_title}\",\n  \"content\": \"HTML 형식의 섹션 내용 (제목 제외)\",\n  \"image_prompt\": \"이 섹션을 위한 상세한 이미지 프롬프트 (한국어, 100자 이상 권장)\"\n}}\n```"
                retry_text = self.gpt(
                    user_content=retry_prompt,
                    temperature=0.3,
                    max_tokens=900,
                )
                json_block = self.extract_json_from_text(retry_text)
                if not json_block:
                    print(f"❌ 재시도 후에도 JSON 블록 없음 - 대체 방법 시도")
                    fallback_data = self.create_fallback_section_data(section_title, retry_text or response_text)
                    if fallback_data:
                        print(f"✅ 대체 방법으로 섹션 데이터 생성 성공")
                        return fallback_data
                    else:
                        raise ValueError("JSON 형식이 감지되지 않음")

            if json_block and json_block.strip():
                section_data = None
                
                try:
                    section_data = json5.loads(json_block)
                except Exception as e:
                    print(f"⚠️ json5 파싱 실패: {e}")
                
                if not section_data:
                    try:
                        section_data = json.loads(json_block)
                    except Exception as e:
                        print(f"⚠️ json 파싱 실패: {e}")
                
                if not section_data:
                    try:
                        cleaned_json = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_block)
                        cleaned_json = re.sub(r'[^\x20-\x7e]', '', cleaned_json)
                        section_data = json.loads(cleaned_json)
                    except Exception as e:
                        print(f"⚠️ 정리된 json 파싱 실패: {e}")
                
                if not section_data:
                    print(f"❌ 모든 JSON 파싱 방법 실패")
                    fallback_data = self.create_fallback_section_data(section_title, response_text)
                    if fallback_data:
                        print(f"✅ 대체 방법으로 섹션 데이터 생성 성공")
                        return fallback_data
                    else:
                        raise ValueError("JSON 파싱에 실패했습니다")
                
                print(f"✅ 섹션 JSON 파싱 성공!")
                
                if not isinstance(section_data, dict):
                    raise ValueError("섹션 데이터가 딕셔너리가 아닙니다")
                
                if "section_title" not in section_data or "content" not in section_data:
                    raise ValueError("섹션 데이터에 필수 필드가 없습니다")
                
                section_title_parsed = str(section_data.get("section_title", ""))
                content = str(section_data.get("content", ""))
                
                if not section_title_parsed or not content:
                    raise ValueError("섹션 제목이나 내용이 비어있습니다")

                try:
                    import re as _re
                    plain = _re.sub(r'<[^>]+>', '', content).strip()
                except Exception:
                    plain = content
                if len(plain) < 300:
                    print(f"⚠️ 본문 길이 부족({len(plain)}자) - 재생성 시도")
                    reinforce_prompt = section_prompt + "\n\n반드시 content를 최소 300자 이상으로 작성하고, JSON만 출력하세요."
                    retry_text = self.gpt(
                        user_content=reinforce_prompt,
                        temperature=0.3,
                        max_tokens=900,
                    )
                    retry_json = self.extract_json_from_text(retry_text)
                    if retry_json:
                        try:
                            try:
                                section_data_retry = json5.loads(retry_json)
                            except Exception:
                                section_data_retry = json.loads(retry_json)
                            section_title_parsed = str(section_data_retry.get("section_title", section_title_parsed))
                            content = str(section_data_retry.get("content", content))
                            image_prompt = section_data_retry.get("image_prompt", section_data.get("image_prompt", ""))
                        except Exception:
                            pass
                
                image_prompt = section_data.get("image_prompt", "")
                if image_prompt:
                    print(f"🎨 섹션에서 추출된 이미지 프롬프트: {image_prompt}")
                else:
                    print(f"⚠️ 섹션에서 이미지 프롬프트가 없습니다")
                
                section_data = {
                    "section_title": section_title_parsed,
                    "content": content,
                    "image_prompt": image_prompt
                }
                
                print(f"✅ 섹션 데이터 생성 완료:")
                print(f"   - 제목: {section_title_parsed}")
                print(f"   - 내용 길이: {len(content)}자")
                print(f"   - 이미지 프롬프트 길이: {len(image_prompt)}자")
                
                return section_data
            else:
                raise ValueError("JSON 블록이 비어있습니다")
            
        except Exception as e:
            raise Exception(f"섹션 내용 생성 실패: {e}")
    
    def create_section_html_without_image(self, section_data):
        """이미지 없이 섹션 HTML을 생성하는 함수"""
        section_title = section_data["section_title"]
        content = section_data["content"]
        
        if "<h2>" in content:
            return content
        else:
            html = f"<h2>{section_title}</h2>\n{content}\n"
            return html
    
    def generate_blog_post(self, keyword, product_url=None, coupang_product=None):
        """
        메인 블로그 글 생성 함수 (gpt_chat_interface.py의 send_to_gpt와 동일)
        
        Args:
            keyword: 블로그 주제 키워드
            product_url: 상품 URL (선택)
            coupang_product: 쿠팡 상품 정보 딕셔너리 (선택)
        
        Returns:
            tuple: (title, content, category) 또는 None
        """
        try:
            product_keyword = keyword
            self._current_coupang_product = coupang_product
            
            if coupang_product:
                product_name = coupang_product.get("name", coupang_product.get("title", keyword))
                product_keyword = product_name
                print(f"🛒 쿠팡 상품 정보 사용: {product_name}")
            
            print(f"🔍 웹 데이터 수집을 시작합니다...")
            
            try:
                import sys
                import os
                
                try:
                    from blog_html_generator.web_search import collect_search_data as web_search_collect
                except ImportError:
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    web_search_path = os.path.join(current_dir, 'blog_html_generator')
                    sys.path.insert(0, web_search_path)
                    from web_search import collect_search_data as web_search_collect
                
                search_keywords = self.generate_optimal_search_keywords_for_main(product_keyword)
                
                print(f"🔍 '{search_keywords}' 구글/빙 검색 중...")
                
                collected_data, urls = web_search_collect(
                    search_keywords, 
                    max_results=10, 
                    return_urls=True,
                    product_url=product_url
                )
                self.collected_urls = urls
                print(f"🔗 수집된 URL 목록: {urls}")
                
                if not collected_data or len(collected_data) < 100:
                    print(f"⚠️ 웹 검색 데이터가 부족합니다: {len(collected_data) if collected_data else 0}자")
                    collected_data = collected_data if collected_data else ""
                
                print(f"✅ 웹 데이터 수집 완료: {len(collected_data)}자")
                
                if collected_data and len(collected_data) >= 100:
                    print("🤖 수집된 데이터를 GPT로 정리합니다...")
                    organized_data = self.organize_collected_data_with_gpt(product_keyword, collected_data)
                    self.collected_web_data = organized_data
                else:
                    organized_data = collected_data
                    self.collected_web_data = organized_data
                
                clean_trimmed_text = product_keyword
                
            except Exception as e:
                print(f"❌ 웹 데이터 수집 실패: {e}")
                import traceback
                traceback.print_exc()
                clean_trimmed_text = product_keyword
            
            print("🤖 GPT에게 글 생성을 요청합니다...")
            
            try:
                from prompt_templates import get_blog_prompt_template
                prompt = get_blog_prompt_template(product_keyword, clean_trimmed_text)
                
                if coupang_product:
                    product_name = coupang_product.get("name", coupang_product.get("title", ""))
                    product_url_val = coupang_product.get("url", coupang_product.get("link", coupang_product.get("product_url", "")))
                    product_image = coupang_product.get("image", coupang_product.get("image_url", coupang_product.get("thumbnail", "")))
                    product_description = coupang_product.get("description", coupang_product.get("desc", ""))
                    product_price = coupang_product.get("price", coupang_product.get("price_text", ""))
                    
                    coupang_info = f"""
🛒 **쿠팡 상품 정보**:
- 상품명: {product_name}
- 상품 링크: {product_url_val}
- 상품 이미지: {product_image}
"""
                    if product_description:
                        coupang_info += f"- 상품 설명: {product_description}\n"
                    if product_price:
                        coupang_info += f"- 가격: {product_price}\n"
                    
                    coupang_info += """
위 쿠팡 상품 정보를 바탕으로 이 상품에 대한 블로그 글을 작성해주세요.
상품의 특징, 장점, 사용법, 추천 이유 등을 포함하여 작성하되, 자연스럽고 읽기 쉬운 형태로 작성해주세요.
상품 링크와 이미지는 글 내용에 자연스럽게 포함시켜주세요.
"""
                    prompt += coupang_info
                    
            except ImportError:
                prompt = f"""
🎯 **사용자 요청 사항 (가장 중요)**:
사용자가 요청한 주제: "{product_keyword}"

이 요청 사항을 반드시 중심으로 하여 글을 작성해주세요.
사용자가 원하는 내용과 방향성을 정확히 파악하여 작성하세요.

당신은 전문적인 블로그 작성자입니다. 주어진 주제와 키워드를 바탕으로 
구조화되고 읽기 쉬운 블로그 포스트를 작성해주세요.

**작성 요구사항:**
1. **주제**: {product_keyword}
2. **키워드**: {clean_trimmed_text}
3. **구조**: 제목, 소개, 본문(4-5개 섹션), 결론
4. **스타일**: 친근하고 전문적인 톤
5. **길이**: 적절한 분량 (너무 길지도 짧지도 않게)

📋 **자유로운 문단 구성 및 중복 방지**:
문단 구성은 자유롭게 하되, 다음 원칙을 따라주세요:

1. **이전 작성된 내용 참고**: 앞서 작성된 모든 내용을 참고하여 중복을 방지
2. **자연스러운 전개**: 기존 내용을 바탕으로 새로운 관점이나 정보를 추가
3. **연결성 유지**: "앞서 언급한", "이러한 배경에서" 등의 연결어로 자연스럽게 연결
4. **새로운 정보 중심**: 이전에 언급하지 않은 새로운 정보, 관점, 분석을 제공

문단의 주제나 방향은 자유롭게 설정하되, 반드시 이전 내용과의 중복을 피해주세요.

**수집된 웹 데이터 활용:**
수집된 웹 데이터를 활용하여 신뢰할 수 있는 정보를 제공하세요.

위 요구사항에 따라 "{product_keyword}" 주제의 블로그 포스트를 작성해주세요.
"""
                
                if coupang_product:
                    product_name = coupang_product.get("name", coupang_product.get("title", ""))
                    product_url_val = coupang_product.get("url", coupang_product.get("link", coupang_product.get("product_url", "")))
                    product_image = coupang_product.get("image", coupang_product.get("image_url", coupang_product.get("thumbnail", "")))
                    product_description = coupang_product.get("description", coupang_product.get("desc", ""))
                    product_price = coupang_product.get("price", coupang_product.get("price_text", ""))
                    
                    coupang_info = f"""
🛒 **쿠팡 상품 정보**:
- 상품명: {product_name}
- 상품 링크: {product_url_val}
- 상품 이미지: {product_image}
"""
                    if product_description:
                        coupang_info += f"- 상품 설명: {product_description}\n"
                    if product_price:
                        coupang_info += f"- 가격: {product_price}\n"
                    
                    coupang_info += """
위 쿠팡 상품 정보를 바탕으로 이 상품에 대한 블로그 글을 작성해주세요.
상품의 특징, 장점, 사용법, 추천 이유 등을 포함하여 작성하되, 자연스럽고 읽기 쉬운 형태로 작성해주세요.
상품 링크와 이미지는 글 내용에 자연스럽게 포함시켜주세요.
"""
                    prompt += coupang_info
            
            prompt += """

중요: 아래 JSON 형식으로만 응답하세요. 다른 설명/텍스트 금지. 반드시 코드펜스 ```json 으로 감싸서 출력.
```json
{
  "section_titles": ["섹션1 제목", "섹션2 제목", "섹션3 제목", "섹션4 제목", "섹션5 제목"],
  "final_title": "최종 제목"
}
```
"""

            response = self.call_chat_with_fallback(
                messages=[{"role": "user", "content": prompt}],
                primary_model=self.config.get("chat_model", "gpt-4o-mini"),
                temperature=1,
            )
            
            response_text = (response.choices[0].message.content or "").strip()
            if not response_text:
                retry_prompt = "필수: 위 요구사항에 따라 JSON만 출력하세요. 설명 금지."
                response = self.call_chat_with_fallback(
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "user", "content": retry_prompt}
                    ],
                    primary_model=self.config.get("chat_model", "gpt-4o-mini"),
                    temperature=1,
                )
                response_text = (response.choices[0].message.content or "").strip()
            
            print("✅ GPT 응답 받음")
            
            section_titles, final_title = self.parse_article_structure(response_text, product_keyword)
            
            title = final_title
            keywords = [product_keyword]
            
            # GPT로 카테고리 추천
            try:
                category_list = [
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
                
                category_prompt = f"""
다음 블로그 포스트 제목과 내용을 분석하여 가장 적합한 카테고리를 추천해주세요.

📝 제목: {title}
📄 내용 요약: {clean_trimmed_text[:500]}...

📋 사용 가능한 카테고리 목록:
"""
                
                for cat in category_list:
                    category_prompt += f"- {cat['ca_name']}: {cat['ca_description']}\n"
                
                category_prompt += """
위 카테고리 중에서 가장 적합한 하나를 선택하여 카테고리명만 출력해주세요.
예시: GameNews
"""
                
                recommended_category = self.gpt(
                    user_content=category_prompt,
                    system_content="블로그 포스트의 내용을 분석하여 가장 적합한 카테고리를 추천하는 전문가입니다.",
                    temperature=0.3,
                    max_tokens=50,
                )
                
                valid_ca_names = [item["ca_name"] for item in category_list]
                if recommended_category in valid_ca_names:
                    category = recommended_category
                    print(f"🤖 GPT 카테고리 추천: {category}")
                else:
                    category = "AMERICAAI"
                    print(f"⚠️ 추천된 카테고리가 유효하지 않음: {recommended_category}, 기본값 사용: {category}")
                    
            except Exception as e:
                category = "AMERICAAI"
                print(f"⚠️ 카테고리 추천 실패: {e}, 기본값 사용: {category}")
            
            print(f"📝 제목: {title}")
            print(f"📂 카테고리: {category}")
            print(f"🏷️ 키워드: {', '.join(keywords)}")

            # 1단계: 모든 섹션 내용을 먼저 완성
            content_parts = []
            section_data_list = []
            previous_sections_content = ""
            
            for i, section_title in enumerate(section_titles):
                try:
                    section_data = self.generate_section_content(section_title, final_title, keyword, clean_trimmed_text, i, previous_sections_content)
                    section_data_list.append(section_data)
                    
                    html = self.create_section_html_without_image(section_data)
                    content_parts.append(html)
                    
                    if section_data and "content" in section_data:
                        current_section_text = section_data["content"]
                        import re
                        clean_text = re.sub(r'<[^>]+>', '', current_section_text)
                        previous_sections_content += f"\n\n{clean_text}"
                    
                    print(f"✅ 섹션 {i+1} 내용 생성 완료")
                except Exception as e:
                    print(f"❌ 섹션 {i+1} 내용 생성 실패: {e}")
                    content_parts.append(f"<h2>{section_titles[i]}</h2>\n<p>이 섹션의 내용을 생성하는 중 오류가 발생했습니다.</p>")
                    section_data_list.append({"section_title": section_titles[i], "content": "오류 발생"})
            
            content = "\n\n".join(content_parts)
            
            print(f"📄 내용 생성 완료: {len(content)}자")
            
            return title, content, category
            
        except Exception as e:
            print(f"❌ 블로그 생성 오류: {e}")
            import traceback
            traceback.print_exc()
            return None


if __name__ == "__main__":
    # 테스트 코드
    generator = BlogGeneratorGPTStyle()
    result = generator.generate_blog_post("네이쳐러브메레 친환경 오리지널 유아 세제")
    if result:
        title, content, category = result
        print(f"\n✅ 생성 완료!")
        print(f"제목: {title}")
        print(f"카테고리: {category}")
        print(f"내용 길이: {len(content)}자")
    else:
        print("❌ 생성 실패")

