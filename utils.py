# -*- coding: utf-8 -*-
"""
유틸리티 함수들
메인 파일에서 분리된 함수들을 모아둔 모듈
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os
import re
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# moviepy는 조건부로 import
try:
    from moviepy.editor import VideoFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    print("⚠️ moviepy 모듈이 없습니다. 비디오 변환 기능이 제한됩니다.")

# Playwright는 조건부로 import
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️ playwright 모듈이 없습니다. 웹 수집 기능이 제한됩니다.")


def collect_google_trends():
    """
    구글 트렌드를 수집하여 뉴스 제목만 반환 (최적화 버전)
    
    Returns:
        str: 쉼표로 구분된 뉴스 제목 문자열
    """
    try:
        url = "https://trends.google.co.kr/trending/rss?geo=KR"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
        }
        
        print("🔍 구글 트렌드 수집 시작...")
        
        # 연결 풀 사용으로 성능 향상
        session = requests.Session()
        session.headers.update(headers)
        
        # 타임아웃 단축 (5초)
        response = session.get(url, timeout=5)
        response.raise_for_status()
        
        # 응답 크기 체크 (너무 큰 응답 방지)
        if len(response.content) > 1024 * 1024:  # 1MB 제한
            print("⚠️ 응답이 너무 큽니다. 수집을 건너뜁니다.")
            return ""
        
        # XML 파싱 (네임스페이스 처리)
        root = ET.fromstring(response.content)
        
        # 네임스페이스 정의
        namespaces = {
            'ht': 'https://trends.google.com/trending/rss'
        }
        
        # RSS 아이템에서 뉴스 제목만 추출 (최대 5개로 제한)
        news_titles = []
        items = root.findall('.//item')[:5]  # 최대 5개만 처리
        
        for item in items:
            # 첫 번째 뉴스 제목 추출 (네임스페이스 사용)
            news_title_elem = item.find('.//ht:news_item_title', namespaces)
            if news_title_elem is not None and news_title_elem.text:
                news_title = news_title_elem.text.strip()
                if news_title and len(news_title) > 1 and len(news_title) < 100:  # 길이 제한
                    news_titles.append(news_title)
        
        # 상위 5개만 선택 (부하 감소)
        news_titles = news_titles[:5]
        
        if news_titles:
            result = ', '.join(news_titles)
            print(f"✅ 구글 트렌드 수집 완료: {len(news_titles)}개 뉴스 제목")
            return result
        else:
            print("⚠️ 구글 트렌드에서 뉴스 제목을 찾을 수 없습니다.")
            return ""
            
    except requests.RequestException as e:
        print(f"❌ 구글 트렌드 요청 오류: {e}")
        return ""
    except ET.ParseError as e:
        print(f"❌ XML 파싱 오류: {e}")
        return ""
    except Exception as e:
        print(f"❌ 구글 트렌드 수집 중 오류: {e}")
        return ""
    finally:
        # 세션 정리
        if 'session' in locals():
            session.close()


def search_web_content(search_keywords, max_results=3):
    """
    웹 검색을 통해 관련 내용을 수집하는 함수
    
    Args:
        search_keywords (str): 검색 키워드
        max_results (int): 최대 결과 수 (기본값: 3)
    
    Returns:
        list: 수집된 웹 콘텐츠 리스트 (dict 형태)
    """
    try:
        print(f"🔍 웹 검색 시작: {search_keywords}")
        
        # 검색 결과 수집
        search_results = []
        
        # 1. Bing 검색 결과 수집
        bing_results = search_bing(search_keywords, max_results)
        search_results.extend(bing_results)
        
        # 2. Naver 검색 결과 수집
        naver_results = search_naver(search_keywords, max_results)
        search_results.extend(naver_results)
        
        # 중복 제거 및 정렬
        unique_results = remove_duplicate_results(search_results)
        
        # 최대 결과 수로 제한
        final_results = unique_results[:max_results]
        
        print(f"✅ 웹 검색 완료: {len(final_results)}개 결과 수집")
        return final_results
        
    except Exception as e:
        print(f"❌ 웹 검색 중 오류: {e}")
        return []


def search_bing(search_keywords, max_results=3):
    """Bing 검색 결과 수집"""
    try:
        # Bing 검색 URL 생성
        encoded_keywords = quote_plus(search_keywords)
        search_url = f"https://www.bing.com/search?q={encoded_keywords}&format=rss"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8'
        }
        
        session = requests.Session()
        session.headers.update(headers)
        
        response = session.get(search_url, timeout=10)
        response.raise_for_status()
        
        # RSS 파싱
        root = ET.fromstring(response.content)
        results = []
        
        items = root.findall('.//item')[:max_results]
        for item in items:
            title_elem = item.find('title')
            link_elem = item.find('link')
            description_elem = item.find('description')
            
            if title_elem is not None and link_elem is not None:
                title = title_elem.text.strip() if title_elem.text else ""
                url = link_elem.text.strip() if link_elem.text else ""
                description = description_elem.text.strip() if description_elem and description_elem.text else ""
                
                # 웹 페이지 내용 수집
                content = extract_web_content(url)
                
                results.append({
                    'title': title,
                    'url': url,
                    'description': description,
                    'content': content,
                    'source': 'bing'
                })
        
        session.close()
        return results
        
    except Exception as e:
        print(f"❌ Bing 검색 중 오류: {e}")
        return []


def search_naver(search_keywords, max_results=3):
    """Naver 검색 결과 수집"""
    try:
        # Naver 검색 URL 생성
        encoded_keywords = quote_plus(search_keywords)
        search_url = f"https://search.naver.com/search.naver?where=news&query={encoded_keywords}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8'
        }
        
        session = requests.Session()
        session.headers.update(headers)
        
        response = session.get(search_url, timeout=10)
        response.raise_for_status()
        
        # HTML 파싱
        soup = BeautifulSoup(response.content, 'html.parser')
        results = []
        
        # 뉴스 결과 추출
        news_items = soup.find_all('div', class_='news_wrap')[:max_results]
        
        for item in news_items:
            title_elem = item.find('a', class_='news_tit')
            link_elem = item.find('a', class_='news_tit')
            description_elem = item.find('div', class_='news_dsc')
            
            if title_elem and link_elem:
                title = title_elem.get_text(strip=True)
                url = link_elem.get('href', '')
                description = description_elem.get_text(strip=True) if description_elem else ""
                
                # 웹 페이지 내용 수집
                content = extract_web_content(url)
                
                results.append({
                    'title': title,
                    'url': url,
                    'description': description,
                    'content': content,
                    'source': 'naver'
                })
        
        session.close()
        return results
        
    except Exception as e:
        print(f"❌ Naver 검색 중 오류: {e}")
        return []


def extract_web_content(url, max_length=1000):
    """
    웹 페이지에서 주요 내용을 추출하는 함수
    
    Args:
        url (str): 웹 페이지 URL
        max_length (int): 최대 추출 길이
    
    Returns:
        str: 추출된 텍스트 내용
    """
    try:
        if not url or not url.startswith('http'):
            return ""
        
        # Playwright 사용 (가능한 경우)
        if PLAYWRIGHT_AVAILABLE:
            return extract_content_with_playwright(url, max_length)
        else:
            return extract_content_with_requests(url, max_length)
            
    except Exception as e:
        print(f"❌ 웹 페이지 내용 추출 중 오류: {e}")
        return ""


def extract_content_with_playwright(url, max_length=1000):
    """Playwright를 사용한 웹 페이지 내용 추출"""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # 페이지 로드
            page.goto(url, timeout=15000)
            page.wait_for_timeout(2000)
            
            # 네이버 블로그인 경우 iframe 처리
            if "blog.naver.com" in url:
                try:
                    page.wait_for_selector("iframe#mainFrame", timeout=5000)
                    frame = page.frame(name="mainFrame")
                    if frame:
                        html = frame.content()
                    else:
                        html = page.content()
                except:
                    html = page.content()
            else:
                html = page.content()
            
            browser.close()
            
            # HTML 파싱 및 텍스트 추출
            soup = BeautifulSoup(html, 'html.parser')
            
            # 불필요한 요소 제거
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                element.decompose()
            
            # 주요 콘텐츠 영역 찾기
            content_selectors = [
                'article', 'main', '.content', '.post-content', '.entry-content',
                '.article-content', '.post-body', '.entry-body', '.main-content'
            ]
            
            content_text = ""
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    for element in elements:
                        text = element.get_text(separator=' ', strip=True)
                        if len(text) > len(content_text):
                            content_text = text
            
            # 주요 콘텐츠를 찾지 못한 경우 전체 텍스트 사용
            if not content_text:
                content_text = soup.get_text(separator=' ', strip=True)
            
            # 텍스트 정리
            content_text = re.sub(r'\s+', ' ', content_text)
            content_text = content_text.strip()
            
            # 길이 제한
            if len(content_text) > max_length:
                content_text = content_text[:max_length] + "..."
            
            return content_text
            
    except Exception as e:
        print(f"❌ Playwright 내용 추출 중 오류: {e}")
        return ""


def extract_content_with_requests(url, max_length=1000):
    """Requests를 사용한 웹 페이지 내용 추출"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8'
        }
        
        session = requests.Session()
        session.headers.update(headers)
        
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        # HTML 파싱
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 불필요한 요소 제거
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            element.decompose()
        
        # 텍스트 추출
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # 길이 제한
        if len(text) > max_length:
            text = text[:max_length] + "..."
        
        session.close()
        return text
        
    except Exception as e:
        print(f"❌ Requests 내용 추출 중 오류: {e}")
        return ""


def remove_duplicate_results(results):
    """중복된 검색 결과 제거"""
    seen_urls = set()
    unique_results = []
    
    for result in results:
        url = result.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(result)
    
    return unique_results


def convert_video_to_mp4_and_upload(video_path, max_duration=8, fps=10, width=800):
    """
    비디오를 MP4 → GIF로 변환하고 GitHub에 업로드
    
    Args:
        video_path (str): 비디오 파일 경로
        max_duration (int): 최대 길이 (초)
        fps (int): 프레임 수
        width (int): 너비 (높이는 비율에 맞춰 자동 조정)
    
    Returns:
        tuple: (github_url, thumb_url) 또는 (None, None) - 항상 GIF URL 반환
    """
    if not MOVIEPY_AVAILABLE:
        print("❌ moviepy 모듈이 없어 비디오 변환을 수행할 수 없습니다.")
        return None, None
    
    try:
        import tempfile
        
        print(f"🎬 MP4 → GIF 변환 시작: {video_path}")
        print(f"   설정: 최대 {max_duration}초, {fps}fps, 너비 {width}px")
        
        # 🆕 파일 자동 수정 시도
        try:
            from video_converter import auto_fix_video_file
            fixed_video_path = auto_fix_video_file(video_path)
            
            if fixed_video_path and fixed_video_path != video_path:
                print(f"🔧 파일 수정됨: {video_path} → {fixed_video_path}")
                video_path = fixed_video_path
        except ImportError:
            print("⚠️ video_converter 모듈을 찾을 수 없습니다.")
        
        # 비디오 로드
        with VideoFileClip(video_path) as video:
            # 길이 제한
            if video.duration > max_duration:
                video = video.subclip(0, max_duration)
            
            # 해상도 조정
            if video.w > width:
                video = video.resize(width=width)
            
            # 임시 MP4 파일 생성
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            mp4_filename = f"video_{timestamp}.mp4"
            mp4_path = os.path.join("E:/Ai project/nb_wfa/chatbot/image", mp4_filename)
            
            # MP4로 저장
            video.write_videofile(
                mp4_path,
                fps=fps,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile='temp-audio.m4a',
                remove_temp=True
            )
            
            print(f"✅ MP4 변환 완료: {mp4_path}")
            
            # 🆕 MP4 → GIF 변환
            gif_filename = f"video_{timestamp}.gif"
            gif_path = os.path.join("E:/Ai project/nb_wfa/chatbot/image", gif_filename)
            
            print(f"🎞️ GIF 변환 시작: {mp4_path} → {gif_path}")
            
            # GIF로 변환 (더 낮은 fps로 파일 크기 줄이기)
            gif_fps = min(fps, 8)  # GIF는 8fps 이하 권장
            video.write_gif(
                gif_path,
                fps=gif_fps,
                program='ffmpeg',
                opt='optimizeplus'
            )
            
            print(f"✅ GIF 변환 완료: {gif_path}")
            
            # 🗑️ 임시 MP4 파일 삭제
            try:
                os.remove(mp4_path)
                print(f"🗑️ 임시 MP4 파일 삭제: {mp4_path}")
            except:
                pass
            
            # GIF를 GitHub에 업로드
            try:
                from github_uploader import upload_image_to_github
                result = upload_image_to_github(gif_path, gif_filename, save_thumb=False)
                if isinstance(result, tuple):
                    github_url, thumb_url = result
                else:
                    github_url = result
                    thumb_url = None
                
                print(f"✅ GIF GitHub 업로드 완료: {github_url}")
                return github_url, thumb_url
            except ImportError:
                print("⚠️ github_uploader 모듈을 찾을 수 없습니다.")
                return None, None
            
    except Exception as e:
        print(f"❌ MP4 → GIF 변환 중 오류: {e}")
        print(f"🔧 자동 수정 시도 중...")
        
        # 🆕 오류 발생 시 자동 수정 재시도
        try:
            from video_converter import auto_fix_video_file
            fixed_video_path = auto_fix_video_file(video_path)
            
            if fixed_video_path and fixed_video_path != video_path:
                print(f"🔄 수정된 파일로 재시도: {fixed_video_path}")
                return convert_video_to_mp4_and_upload(fixed_video_path, max_duration, fps, width)
        except Exception as fix_error:
            print(f"❌ 자동 수정도 실패: {fix_error}")
        
        return None, None


def get_driver(headless=True):
    """Selenium 드라이버를 가져오는 함수"""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except ImportError:
        print("❌ Selenium이 설치되지 않았습니다.")
        return None


def draw_caption_with_shadow(img, text, font_path=r"E:\Ai project\nb_wfa\chatbot\full_screenshot\NanumGothic.ttf", font_size=20, padding=50):
    """이미지에 자막을 추가하는 함수"""
    from PIL import ImageDraw, ImageFont
    
    # 하단에 검은색 배경 추가 (이미지 높이 증가)
    new_height = img.height + padding
    new_img = Image.new("RGB", (img.width, new_height), color="black")
    new_img.paste(img, (0, 0))

    draw = ImageDraw.Draw(new_img)

    # 폰트 설정
    try:
        font = ImageFont.truetype(font_path, font_size)
    except:
        font = ImageFont.load_default()
        print("⚠️ NanumGothic.ttf 폰트를 찾을 수 없습니다. 기본 폰트를 사용합니다.")

    # 텍스트 크기 계산
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except AttributeError:
        text_width, text_height = font.getsize(text)

    # 텍스트 위치: 하단 중앙
    x = (new_img.width - text_width) // 2
    y = img.height + (padding - text_height) // 2

    # 그림자 효과
    for dx in [-1, 1]:
        for dy in [-1, 1]:
            draw.text((x + dx, y + dy), text, font=font, fill="gray")

    # 실제 텍스트
    draw.text((x, y), text, font=font, fill="white")

    return new_img


def is_image_similar(img1, img2, threshold=0.8):
    """이미지 해시 기반 유사도 비교"""
    import imagehash
    hash1 = imagehash.average_hash(img1)
    hash2 = imagehash.average_hash(img2)
    similarity = 1 - (hash1 - hash2) / len(hash1.hash) ** 2
    return similarity >= threshold


def count_text_characters_in_image(image):
    """이미지에서 텍스트 문자 수를 세는 함수"""
    # 간단한 구현 - 실제로는 OCR이 필요
    return 0, ""


def download_bing_images_for_sora(search_query, max_images=5, output_filename="bing_sora_reference.png"):
    """
    Bing 이미지를 Sora ChatGPT에서 사용하기 위해 다운로드하는 함수
    
    Parameters:
        search_query (str): 검색어
        max_images (int): 최대 이미지 수 (Sora용으로는 적은 수가 적합)
        output_filename (str): 출력 파일명
    
    Returns:
        dict: Sora ChatGPT에서 사용할 수 있는 정보
    """
    print(f"🎬 Bing + Sora 모드 시작: {search_query}")

    import random, urllib.parse, json, time
    import requests
    from io import BytesIO
    from PIL import Image

    used_image_urls = set()
    used_images = []

    driver = get_driver(headless=False)
    if driver is None:
        return None
        
    images_downloaded = []

    try:
        from selenium.webdriver.common.by import By
        
        search_query_with_date = f"{search_query}"
        encoded_query = urllib.parse.quote_plus(search_query_with_date)
        bing_url = f"https://www.bing.com/images/search?q={encoded_query}&form=HDRSC3"
        print("🔍 Bing 이미지 검색 URL:", bing_url)
        driver.get(bing_url)
        time.sleep(3)

        print("🔍 일반 이미지 수집 중...")
        general_images = []
        thumb_items = driver.find_elements(By.CSS_SELECTOR, "a.iusc")
        for a in thumb_items:
            try:
                metadata = a.get_attribute("m")
                if metadata:
                    meta_json = json.loads(metadata)
                    image_url = meta_json.get("murl")
                    title = meta_json.get("t", "")
                    if image_url and image_url.startswith("http") and image_url not in used_image_urls:
                        general_images.append({"src": image_url, "title": title, "source": "bing"})
                if len(general_images) >= max_images:
                    break
            except:
                continue
        images_downloaded.extend(general_images)

    finally:
        driver.quit()

    if not images_downloaded:
        print("❌ 다운로드 성공한 이미지 없음")
        return None

    grid_num = min(3, len(images_downloaded))  # Sora용으로는 3개 정도가 적합
    print(f"🎯 Sora용으로 {grid_num}개의 이미지를 포함합니다.")

    valid_imgs = []
    valid_info = []

    for item in images_downloaded:
        src = item["src"]
        title = item["title"]
        source = item.get("source", "unknown")

        if src in used_image_urls:
            print(f"⚠️ 중복 이미지 URL 건너뜀: {src}")
            continue

        try:
            resp = requests.get(src, timeout=10)
            img = Image.open(BytesIO(resp.content)).convert("RGB")
        except Exception:
            continue

        if any(is_image_similar(img, used_img, threshold=0.8) for used_img in used_images):
            print("⚠️ 이미지 자체 유사도 80% 이상 → 중복 처리됨")
            continue

        print("🔍 이미지 분석 중...")
        count, raw_text = count_text_characters_in_image(img)

        print("✅ 이미지 분석 완료")
        caption = ''
        print("📝 이미지 제목:", title)
        print("📝 이미지 출처:", source)
        print(f"📝 이미지 URL: {src}")

        # Sora 모드: 모든 이미지를 수집 (주제 일치 검사 없음)
        valid_imgs.append(img)
        valid_info.append({
            "img": img,
            "url": src,
            "title": title,
            "caption": caption,
            "match_result": {"result": "sora_mode", "reason": "Sora 모드로 자동 수집"},
            "source": source
        })
        used_image_urls.add(src)
        used_images.append(img)
        print(f"✅ [{source}] Sora 모드로 이미지 추가됨: {title}")

        if len(valid_imgs) >= grid_num:
            print("✅ Sora용 이미지 수량 충족 → 중단")
            break

    if not valid_info:
        print("❌ 수집된 이미지가 없습니다.")
        return None

    # 이미지 개수에 따른 레이아웃 결정
    image_count = len(valid_info)
    
    if image_count == 1:
        # 이미지가 1장인 경우: 원본 크기 유지
        print("🖼️ 이미지 1장: 원본 크기 유지")
        img = valid_info[0]["img"]
        grid_img = img.copy()
    else:
        # 이미지가 2장 이상인 경우: 가로로 붙이기
        print(f"🖼️ 이미지 {image_count}장: 가로로 붙이기")
        
        # 모든 이미지를 동일한 높이로 리사이즈
        target_height = min(im["img"].height for im in valid_info)
        cell_imgs = []
        
        for im_info in valid_info:
            img = im_info["img"]
            # 비율을 유지하면서 높이에 맞춰 리사이즈
            aspect_ratio = img.width / img.height
            new_width = int(target_height * aspect_ratio)
            resized_img = img.resize((new_width, target_height), Image.LANCZOS)
            cell_imgs.append(resized_img)
        
        # 가로로 이미지들을 붙이기
        total_width = sum(img.width for img in cell_imgs)
        grid_img = Image.new("RGB", (total_width, target_height), (255, 255, 255))
        
        x_offset = 0
        for img in cell_imgs:
            grid_img.paste(img, (x_offset, 0))
            x_offset += img.width
        
        # 목표 너비에 맞춰 리사이즈 (비율 유지)
        target_width = 1024
        if total_width > target_width:
            aspect_ratio = total_width / target_height
            new_height = int(target_width / aspect_ratio)
            grid_img = grid_img.resize((target_width, new_height), Image.LANCZOS)
        else:
            # 작은 경우 목표 너비에 맞춰 확대
            aspect_ratio = total_width / target_height
            new_height = int(target_width / aspect_ratio)
            grid_img = grid_img.resize((target_width, new_height), Image.LANCZOS)

    # Sora용 자막 생성
    combined_caption = " / ".join(
        f"Bing 이미지 {i+1}: {info['title'][:30]}..." 
        for i, info in enumerate(valid_info)
    )
    subtitle = f"Sora 모드: {search_query[:50]}..."
    
    grid_img = draw_caption_with_shadow(grid_img, subtitle)
    grid_img.save(output_filename)
    
    # 이미지 개수에 따른 출력 메시지
    if image_count == 1:
        print(f"[단일 이미지 저장] {output_filename}")
    else:
        print(f"[가로 배치 {image_count}장 이미지 저장] {output_filename}")

    # Sora ChatGPT용 프롬프트 생성
    sora_prompts = [
        f"이 이미지를 참고하여 {search_query}에 대한 영상을 생성해주세요. 이미지의 분위기와 구도를 활용하여 자연스러운 움직임을 만들어주세요."
        for _ in valid_info
    ]

    result_data = {
        "grid_path": output_filename,
        "mode": "sora",
        "images": [
            {
                "url": info["url"],
                "title": info["title"],
                "caption": info["caption"],
                "match_result": info["match_result"],
                "source": info["source"]
            }
            for info in valid_info
        ],
        "used_image_urls": list(used_image_urls),
        "sora_prompts": sora_prompts
    }

    print("🎬 Sora ChatGPT용 프롬프트 생성 완료")
    print("✅ Sora 모드 완료!")
    print("📋 Sora ChatGPT에서 사용할 프롬프트:")
    for i, prompt in enumerate(sora_prompts, 1):
        print(f"  {i}. {prompt}")
    
    print(f"🖼️ 참고 이미지 저장됨: {output_filename}")
    print("💡 Sora ChatGPT에서 이 이미지를 업로드하고 위의 프롬프트를 사용하세요!")

    return result_data


def collect_trending_articles_as_text():
    """
    트렌딩 기사를 텍스트로 수집하는 함수
    현재는 collect_google_trends 함수를 호출하여 구글 트렌드를 반환
    """
    return collect_google_trends()


def generate_search_link(keyword, search_engine="bing"):
    """
    검색 엔진에 따른 검색 링크 생성
    
    Args:
        keyword (str): 검색 키워드
        search_engine (str): 검색 엔진 ("bing", "naver", "google")
    
    Returns:
        str: 검색 URL
    """
    from urllib.parse import quote
    
    encoded_keyword = quote(keyword)
    
    if search_engine.lower() == "naver":
        return f"https://search.naver.com/search.naver?query={encoded_keyword}"
    elif search_engine.lower() == "google":
        return f"https://www.google.com/search?q={encoded_keyword}"
    else:  # bing (기본값)
        return f"https://www.bing.com/search?q={encoded_keyword}&sendquery=1&FORM=SCCODX&rh=B0D80A4F&ref=rafsrchae" 