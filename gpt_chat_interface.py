import sys
import os
import json
import openai
import requests
import time
from datetime import datetime, timedelta
import re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QLabel, QHBoxLayout,
    QCheckBox, QGroupBox, QRadioButton, QComboBox,
    QSpinBox, QGridLayout, QButtonGroup, QScrollArea,
    QFrame
)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
import json5
import time
import random
from prompt_utils import build_article_from_existing_structure, build_paragraph_prompt

# OpenAI API 키 설정 (환경 변수 또는 설정 파일에서 로드)
import os
from openai import OpenAI
api_key = os.getenv("OPENAI_API_KEY", "")
if not api_key:
    # 설정 파일에서 로드 시도
    try:
        import json
        config_path = os.path.join(os.path.dirname(__file__), "openai_config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                api_key = config.get("api_key", "")
    except:
        pass
client = OpenAI(api_key=api_key) if api_key else None

# 조건부 import (지연 로딩)
def import_modules_on_demand():
    """필요할 때만 모듈을 import하는 함수"""
    global tistory_auto_writer, image_search, utils, mysql_handler, full_screenshot_gpu
    
    try:
        from tistory_auto_writer import open_tistory_new_post_page, write_post_on_tistory, get_best_category_id_from_gpt, build_category_prompt_with_system
        tistory_auto_writer = True
        print("✅ tistory_auto_writer 모듈 로드 완료")
    except ImportError:
        tistory_auto_writer = False
        print("⚠️ tistory_auto_writer 모듈 로드 실패")
    
    try:
        from image_search import naver_image_search_with_rotation, download_image_with_timestamp, upload_image_to_github, google_image_search_safe
        image_search = True
        print("✅ image_search 모듈 로드 완료")
    except ImportError:
        image_search = False
        print("⚠️ image_search 모듈 로드 실패")
    
    try:
        from utils import collect_google_trends
        utils = True
        print("✅ utils 모듈 로드 완료")
    except ImportError:
        utils = False
        print("⚠️ utils 모듈 로드 실패")
    
    try:
        from mysql_handler import insert_to_mysql
        mysql_handler = True
        print("✅ mysql_handler 모듈 로드 완료")
    except ImportError:
        mysql_handler = False
        print("⚠️ mysql_handler 모듈 로드 실패")
    
    try:
        from full_screenshot.full_screenshot_gpu import download_top_bing_images_grid_match, load_blip_model
        full_screenshot_gpu = True
        print("✅ full_screenshot_gpu 모듈 로드 완료")
    except ImportError:
        full_screenshot_gpu = False
        print("⚠️ full_screenshot_gpu 모듈 로드 실패")

class GoogleTrendsAutoThread(QThread):
    trends_collected = pyqtSignal(str)
    status_updated = pyqtSignal(str)
    countdown_updated = pyqtSignal(str)  # 카운트다운 업데이트 시그널 추가
    
    def __init__(self, interval_minutes=30):
        super().__init__()
        self.interval_minutes = interval_minutes
        self.is_running = False
        self.timer = QTimer()  # 사용하지 않지만 기존 호환성 유지
        self.consecutive_failures = 0
        self.max_failures = 3
        self._first_collection_done = False  # 첫 번째 수집 완료 추적
        self.next_collection_time = None  # 다음 수집 시간 저장
        self.is_collecting = False  # 중복 수집 방지
        
        # 카운트다운용 타이머는 메인 스레드에서 실행
        self.countdown_timer = None  # 나중에 설정
        
    def run(self):
        try:
            print(f"🚀 GoogleTrendsAutoThread 시작 - 간격: {self.interval_minutes}분")
            self.is_running = True
            self.status_updated.emit("🔄 구글 트렌드 자동 수집 시작")
            
            # 첫 수집은 즉시 실행 (카운트다운은 멀티검색 완료 후 시작)
            self.next_collection_time = None
            print("🚚 초기 실행 - 즉시 트렌드 수집")
            try:
                self.is_collecting = True
                self.collect_trends()
            finally:
                self.is_collecting = False
            
            # 카운트다운 업데이트 (1초마다)
            while self.is_running:
                # 시각 도달 시 수집 수행 (QTimer 대신 폴링 방식)
                try:
                    if (self.next_collection_time is not None
                        and datetime.now() >= self.next_collection_time
                        and not self.is_collecting):
                        self.is_collecting = True
                        print("🚚 예정 시간 도달 - 트렌드 수집 실행")
                        self.collect_trends()
                        # 다음 수집 시간은 멀티검색 완료 후 UI에서 설정
                        self.next_collection_time = None
                        self.is_collecting = False
                except Exception as loop_e:
                    print(f"⚠️ 수집 루프 중 예외: {loop_e}")
                    self.is_collecting = False
                self.update_countdown()
                self.msleep(1000)  # 1초마다 체크
            
        except Exception as e:
            print(f"❌ GoogleTrendsAutoThread 오류: {e}")
            self.status_updated.emit(f"❌ 스레드 실행 오류: {str(e)}")
            
    def stop(self):
        self.is_running = False
        self.status_updated.emit("⏹️ 구글 트렌드 자동 수집 중지")
        
    def update_countdown(self):
        """카운트다운 업데이트"""
        if not self.is_running:
            return
        # 멀티검색/작성 진행 중: 다음 수집 예약 전까지 진행중 메시지 표시
        if self.next_collection_time is None:
            self.countdown_updated.emit("⏳ 다음 수집: 작성 중")
            return
            
        now = datetime.now()
        if self.next_collection_time > now:
            remaining = self.next_collection_time - now
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            countdown_text = f"⏳ 다음 수집까지: {minutes:02d}:{seconds:02d}"
            self.countdown_updated.emit(countdown_text)
        else:
            # 시간이 지난 상태: 수집 루프에서 처리하므로 카운트다운만 표시
            self.countdown_updated.emit("⏳ 다음 수집까지: 00:00")
    
    def collect_trends(self):
        """구글 트렌드 수집 실행"""
        if self.consecutive_failures >= self.max_failures:
            self.status_updated.emit(f"⚠️ 연속 {self.max_failures}회 실패로 일시 중지")
            QTimer.singleShot(30 * 60 * 1000, self.reset_failures)
            return
            
        try:
            self.status_updated.emit("🔍 구글 트렌드 수집 중...")
            print(f"🔍 자동 트렌드 수집 시작: {datetime.now().strftime('%H:%M:%S')}")
            
            # 지연 로딩으로 utils 모듈 확인
            if 'utils' in globals() and utils:
                from utils import collect_google_trends
                trends = collect_google_trends()
                if trends and trends.strip():
                    self.trends_collected.emit(trends)
                    self.status_updated.emit(f"✅ 트렌드 수집 완료 ({datetime.now().strftime('%H:%M')})")
                    self.consecutive_failures = 0
                    self._first_collection_done = True  # 첫 번째 수집 완료 표시
                    print(f"✅ 자동 트렌드 수집 성공: {trends[:50]}...")
                    print(f"   - 첫 번째 수집 완료 표시: {self._first_collection_done}")
                else:
                    self.consecutive_failures += 1
                    self.status_updated.emit(f"❌ 트렌드 수집 실패 - 빈 결과 (연속 {self.consecutive_failures}회)")
                    print(f"❌ 자동 트렌드 수집 실패 - 빈 결과 (연속 {self.consecutive_failures}회)")
            else:
                self.status_updated.emit("⚠️ utils 모듈이 로드되지 않았습니다")
                print("⚠️ utils 모듈이 로드되지 않아 자동 트렌드 수집을 건너뜁니다")
                
        except Exception as e:
            self.consecutive_failures += 1
            error_msg = f"❌ 트렌드 수집 오류: {str(e)}"
            self.status_updated.emit(error_msg)
            print(f"❌ 자동 트렌드 수집 오류: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def reset_failures(self):
        self.consecutive_failures = 0
        self.status_updated.emit("🔄 실패 카운트 리셋, 수집 재개")

    def schedule_next_after_completion(self):
        """UI에서 멀티검색 완료 후 호출해 다음 수집 시간을 설정"""
        try:
            self.next_collection_time = datetime.now() + timedelta(minutes=self.interval_minutes)
            print(f"⏰ UI 신호로 다음 수집 시간 설정: {self.next_collection_time.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"⚠️ 다음 수집 시간 설정 실패: {e}")

class CoupangProductAutoThread(QThread):
    products_collected = pyqtSignal(dict)  # 수집된 상품 정보 전달
    status_updated = pyqtSignal(str)
    countdown_updated = pyqtSignal(str)
    
    def __init__(self, interval_minutes=60, json_path=None):
        super().__init__()
        self.interval_minutes = interval_minutes
        self.json_path = json_path
        self.is_running = False
        self.consecutive_failures = 0
        self.max_failures = 3
        self._first_collection_done = False
        self.next_collection_time = None
        self.is_collecting = False
    
    def run(self):
        try:
            print(f"🚀 CoupangProductAutoThread 시작 - 간격: {self.interval_minutes}분")
            self.is_running = True
            self.status_updated.emit("🔄 쿠팡 상품 자동 수집 시작")
            
            # 첫 수집은 즉시 실행
            self.next_collection_time = None
            print("🚚 초기 실행 - 즉시 쿠팡 상품 수집")
            try:
                self.is_collecting = True
                self.collect_products()
            finally:
                self.is_collecting = False
            
            # 카운트다운 업데이트 (1초마다)
            while self.is_running:
                try:
                    if (self.next_collection_time is not None
                        and datetime.now() >= self.next_collection_time
                        and not self.is_collecting):
                        self.is_collecting = True
                        print("🚚 예정 시간 도달 - 쿠팡 상품 수집 실행")
                        self.collect_products()
                        self.next_collection_time = None
                        self.is_collecting = False
                except Exception as loop_e:
                    print(f"⚠️ 수집 루프 중 예외: {loop_e}")
                    self.is_collecting = False
                self.update_countdown()
                self.msleep(1000)  # 1초마다 체크
            
        except Exception as e:
            print(f"❌ CoupangProductAutoThread 오류: {e}")
            self.status_updated.emit(f"❌ 스레드 실행 오류: {str(e)}")
    
    def stop(self):
        self.is_running = False
        self.status_updated.emit("⏹️ 쿠팡 상품 자동 수집 중지")
    
    def update_countdown(self):
        """카운트다운 업데이트"""
        if not self.is_running:
            return
        if self.next_collection_time is None:
            self.countdown_updated.emit("⏳ 다음 수집: 작성 중")
            return
            
        now = datetime.now()
        if self.next_collection_time > now:
            remaining = self.next_collection_time - now
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            countdown_text = f"⏳ 다음 수집까지: {minutes:02d}:{seconds:02d}"
            self.countdown_updated.emit(countdown_text)
        else:
            self.countdown_updated.emit("⏳ 다음 수집까지: 00:00")
    
    def collect_products(self):
        """쿠팡 상품 정보 수집 실행"""
        if self.consecutive_failures >= self.max_failures:
            self.status_updated.emit(f"⚠️ 연속 {self.max_failures}회 실패로 일시 중지")
            QTimer.singleShot(30 * 60 * 1000, self.reset_failures)
            return
            
        try:
            self.status_updated.emit("🔍 쿠팡 상품 정보 수집 중...")
            print(f"🔍 자동 쿠팡 상품 수집 시작: {datetime.now().strftime('%H:%M:%S')}")
            
            # 쿠팡 상품 정보 수집 (실제 구현 필요)
            # 여기서는 JSON 파일을 읽어서 업데이트하는 방식으로 구현
            products_data = self.collect_coupang_products()
            
            if products_data:
                # JSON 파일에 저장 (상품이 있든 없든 last_update는 업데이트)
                if self.json_path:
                    try:
                        # 디렉토리가 없으면 생성
                        json_dir = os.path.dirname(self.json_path)
                        if json_dir and not os.path.exists(json_dir):
                            os.makedirs(json_dir, exist_ok=True)
                        
                        with open(self.json_path, 'w', encoding='utf-8') as f:
                            json.dump(products_data, f, ensure_ascii=False, indent=2)
                        
                        product_count = len(products_data.get("selected", []))
                        if product_count > 0:
                            print(f"✅ 쿠팡 상품 정보 저장 완료: {product_count}개")
                            self.status_updated.emit(f"✅ 상품 수집 완료 ({datetime.now().strftime('%H:%M')}) - {product_count}개")
                        else:
                            print(f"✅ 쿠팡 상품 정보 업데이트 완료 (상품 없음)")
                            self.status_updated.emit(f"✅ 정보 업데이트 완료 ({datetime.now().strftime('%H:%M')}) - 상품 없음")
                    except Exception as save_e:
                        print(f"⚠️ JSON 파일 저장 실패: {save_e}")
                        self.consecutive_failures += 1
                        self.status_updated.emit(f"❌ 파일 저장 실패: {str(save_e)}")
                        return
                
                self.products_collected.emit(products_data)
                self.consecutive_failures = 0
                self._first_collection_done = True
                
                product_count = len(products_data.get("selected", []))
                if product_count > 0:
                    print(f"✅ 자동 쿠팡 상품 수집 성공: {product_count}개 상품")
                else:
                    print(f"✅ 자동 쿠팡 상품 정보 업데이트 완료 (상품 없음 - 실제 수집 로직 필요)")
                
                # 다음 수집 시간 설정 (멀티검색 완료 후 자동으로 시작되도록)
                self.schedule_next_after_completion()
            else:
                self.consecutive_failures += 1
                self.status_updated.emit(f"❌ 상품 수집 실패 - 데이터 없음 (연속 {self.consecutive_failures}회)")
                print(f"❌ 자동 쿠팡 상품 수집 실패 - 데이터 없음 (연속 {self.consecutive_failures}회)")
                
        except Exception as e:
            self.consecutive_failures += 1
            error_msg = f"❌ 상품 수집 오류: {str(e)}"
            self.status_updated.emit(error_msg)
            print(f"❌ 자동 쿠팡 상품 수집 오류: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def collect_coupang_products(self):
        """쿠팡 상품 정보를 실제로 수집하는 함수 (저장된 JSON 파일 사용)"""
        try:
            # 저장된 쿠팡 상품 JSON 파일 경로
            products_json_path = r"E:\Gif\www\참소식.com\gnuboard5.5.8.3.2\theme\nbBasic\parts\data\coupang-products.json"
            
            collected_products = []
            
            # 저장된 JSON 파일에서 상품 정보 읽기
            if os.path.exists(products_json_path):
                try:
                    with open(products_json_path, 'r', encoding='utf-8') as f:
                        products_data = json.load(f)
                    
                    # JSON 구조에 따라 상품 정보 추출
                    # 다양한 가능한 구조 지원
                    if isinstance(products_data, list):
                        # 리스트 형태인 경우
                        collected_products = products_data
                    elif isinstance(products_data, dict):
                        # 딕셔너리 형태인 경우
                        if "products" in products_data:
                            collected_products = products_data["products"]
                        elif "data" in products_data:
                            if isinstance(products_data["data"], list):
                                collected_products = products_data["data"]
                            elif isinstance(products_data["data"], dict) and "products" in products_data["data"]:
                                collected_products = products_data["data"]["products"]
                        elif "selected" in products_data:
                            collected_products = products_data["selected"]
                        elif "items" in products_data:
                            collected_products = products_data["items"]
                        else:
                            # 딕셔너리의 값 중 리스트인 것을 찾기
                            for key, value in products_data.items():
                                if isinstance(value, list) and len(value) > 0:
                                    collected_products = value
                                    break
                    
                    # 상품 정보 정규화 (필요한 필드명 통일)
                    normalized_products = []
                    for product in collected_products:
                        if isinstance(product, dict):
                            normalized_product = {
                                "name": product.get("name") or product.get("productName") or product.get("title") or "",
                                "title": product.get("title") or product.get("productName") or product.get("name") or "",
                                "url": product.get("url") or product.get("productUrl") or product.get("link") or product.get("product_url") or "",
                                "link": product.get("link") or product.get("url") or product.get("productUrl") or product.get("product_url") or "",
                                "product_url": product.get("product_url") or product.get("url") or product.get("productUrl") or product.get("link") or "",
                                "image": product.get("image") or product.get("productImage") or product.get("image_url") or product.get("thumbnail") or "",
                                "image_url": product.get("image_url") or product.get("image") or product.get("productImage") or product.get("thumbnail") or "",
                                "thumbnail": product.get("thumbnail") or product.get("image") or product.get("productImage") or product.get("image_url") or "",
                                "price": product.get("price") or product.get("productPrice") or 0,
                                "price_text": product.get("price_text") or (f"{product.get('price', 0):,}원" if product.get('price') else ""),
                                "description": product.get("description") or product.get("productDescription") or product.get("desc") or "",
                                "desc": product.get("desc") or product.get("description") or product.get("productDescription") or ""
                            }
                            normalized_products.append(normalized_product)
                    
                    collected_products = normalized_products
                    print(f"✅ 쿠팡 상품 JSON 파일 읽기 완료: {len(collected_products)}개 상품")
                    
                except json.JSONDecodeError as e:
                    print(f"⚠️ JSON 파일 파싱 오류: {e}")
                except Exception as e:
                    print(f"⚠️ JSON 파일 읽기 오류: {e}")
            else:
                print(f"⚠️ 쿠팡 상품 JSON 파일을 찾을 수 없습니다: {products_json_path}")
            
            # 수집된 상품이 없으면 기존 selected 파일 확인
            if not collected_products:
                if self.json_path and os.path.exists(self.json_path):
                    try:
                        with open(self.json_path, 'r', encoding='utf-8') as f:
                            existing_data = json.load(f)
                        if existing_data.get("selected"):
                            collected_products = existing_data.get("selected", [])
                            print(f"📦 기존 selected 파일에서 상품 정보 로드: {len(collected_products)}개")
                    except:
                        pass
            
            # 결과 데이터 구성
            result = {
                "last_update": datetime.now().isoformat(),
                "total": len(collected_products),
                "selected": collected_products
            }
            
            return result
            
        except Exception as e:
            print(f"⚠️ 쿠팡 상품 정보 수집 실패: {e}")
            import traceback
            traceback.print_exc()
            
            # 오류 시 기존 데이터 유지 시도
            try:
                if self.json_path and os.path.exists(self.json_path):
                    with open(self.json_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                    if existing_data.get("selected"):
                        return {
                            "last_update": datetime.now().isoformat(),
                            "total": len(existing_data.get("selected", [])),
                            "selected": existing_data.get("selected", [])
                        }
            except:
                pass
            
            # 기본 구조 반환
            return {
                "last_update": datetime.now().isoformat(),
                "total": 0,
                "selected": []
            }
    
    def reset_failures(self):
        self.consecutive_failures = 0
        self.status_updated.emit("🔄 실패 카운트 리셋, 수집 재개")
    
    def schedule_next_after_completion(self):
        """UI에서 멀티검색 완료 후 호출해 다음 수집 시간을 설정"""
        try:
            self.next_collection_time = datetime.now() + timedelta(minutes=self.interval_minutes)
            print(f"⏰ UI 신호로 다음 쿠팡 상품 수집 시간 설정: {self.next_collection_time.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"⚠️ 다음 수집 시간 설정 실패: {e}")

class GPTChatUI(QWidget):
    def __init__(self):
        super().__init__()
        self.messages = []
        self.category = "Uncategorized"
        
        # 실행 제어 변수들
        self.is_running = False
        self.is_paused = False
        self.should_stop = False
        self.used_image_urls = set()

        # 설정 초기화
        self.config = {
            "tistory_enabled": False,
            "naver_enabled": True,
            "image_source": "bing",
            "input_keyword": "",
            "image_prompt_requirements": "4K 고화질, 디테일하고 자세한 이미지, 현실적인 스타일",  # 기본값 설정
            "auto_trends_enabled": False,
            "trends_interval": 30,
            "post_interval_minutes": 1,
            "use_random_probability": False,
            "random_probability": 85,
            "bing_image_count": 3,
            "gif_similarity": 50,
            "gif_inclusion": 50,
            "word_inclusion_threshold": 30,
            "load_control_enabled": True,
            "auto_multi_search_enabled": True,
            "bo_table": "free",
            "ca_name": "AMERICAAI",
            "ad_link": "",
            "use_gpu_for_images": True,
            "chat_model": "gpt-5-mini",
            "coupang_selected_enabled": False,
            "coupang_selected_json_path": r"E:\Gif\www\참소식.com\gnuboard5.5.8.3.2\theme\nbBasic\parts\data\coupang-selected.json",
            "coupang_products_json_path": r"E:\Gif\www\참소식.com\gnuboard5.5.8.3.2\theme\nbBasic\parts\data\coupang-products.json",
            "coupang_image_enabled": False,
            "coupang_link_enabled": False,
            "auto_coupang_enabled": False,
            "coupang_interval": 60,
            "search_engine": "bing"
        }
        self.config_path = os.path.join(os.path.dirname(__file__), "gpt_blog_config.json")
        self.load_config()

        # 자동화 스레드 초기화
        self.auto_trends_thread = None
        self.auto_coupang_thread = None

        # UI 생성
        self.init_ui()
        
        # 모듈 지연 로딩
        self.load_modules_async()
        
        # 자동 수집은 기본/저장 모두 비활성화 상태 유지
        print("⏹️ 자동 트렌드 수집은 기본적으로 비활성화되어 있습니다.")
        if hasattr(self, 'next_collection_label'):
            self.next_collection_label.setText("⏳ 다음 수집: --:--")

    def _sanitize_filename(self, text: str, max_length: int = 100) -> str:
        """Windows 안전 파일명 생성: 금지문자 제거, 공백→'_', 길이 제한"""
        try:
            import re
            if not text:
                return "file"
            # HTML 제거
            text = re.sub(r"<[^>]+>", " ", str(text))
            # 금지문자 제거
            text = re.sub(r"[\\/:*?\"<>|]", " ", text)
            # 연속 공백/언더스코어 정리
            text = re.sub(r"\s+", " ", text).strip()
            text = text.replace(" ", "_")
            # 너무 긴 경우 자르기
            if len(text) > max_length:
                text = text[:max_length].rstrip("_-")
            return text or "file"
        except Exception:
            return "file"

    def call_chat_with_fallback(self, messages, primary_model="gpt-5-mini", temperature=0.3, max_tokens=500):
        """모델/파라미터 호환성 처리. 모델은 gpt-5-mini만 사용(폴백 제거).
        - 토큰 파라미터: (생략) → max_tokens → max_completion_tokens 순 시도
        - temperature: 요청값 → 1 → 생략 순 시도
        """
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
                        # 파라미터 미지원: 동일 모델에서 대체 파라미터/모드 시도
                        if (
                            "Unsupported parameter" in err
                            and ("max_tokens" in err or "max_completion_tokens" in err)
                        ):
                            print(f"⚠️ 모델 '{model_name}'에서 '{token_param}' 미지원 → 대체 토큰 파라미터 시도")
                            break  # 다음 토큰 파라미터 시도
                        if (
                            "Unsupported value" in err and "temperature" in err
                        ):
                            print(f"⚠️ 모델 '{model_name}'에서 temperature 값 미지원 → 대체 temperature 모드 시도")
                            continue  # 다음 temperature 모드 시도
                        # 모델 미지원/권한 없음/403이면 다음 모델로 폴백
                        if (
                            "model_not_found" in err
                            or "does not have access" in err
                            or "403" in err
                        ):
                            print(f"⚠️ 모델 '{model_name}' 사용 불가, 다음 후보로 폴백: {err}")
                            break  # 다음 모델 시도
                        # 기타 오류는 그대로 전파
                        raise
        raise Exception("사용 가능한 모델이 없습니다. 허용 모델 및 권한을 확인하세요.")

    def gpt(self, user_content: str, system_content: str = None, temperature: float = 0.3,
            max_tokens: int = 500, primary_model: str = None) -> str:
        """단일 GPT 호출 함수: system/user를 받아 텍스트 응답(content)만 반환"""
        messages = []
        if system_content:
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": user_content})
        # 기본 모델은 설정된 chat_model 사용
        if not primary_model:
            primary_model = self.config.get("chat_model", "gpt-5-mini")
        resp = self.call_chat_with_fallback(
            messages=messages,
            primary_model=primary_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    def load_modules_async(self):
        """비동기로 모듈들을 로드"""
        import_modules_on_demand()

    def init_ui(self):
        self.setWindowTitle("🧠 GPT 블로그 작성기 (최적화 버전)")
        self.setGeometry(300, 100, 1200, 800)  # 창 크기 조정 (가로 늘리고 세로 줄임)

        # 메인 레이아웃
        main_layout = QVBoxLayout()
        
        # 스크롤 영역 생성
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setMinimumHeight(700)  # 최소 높이 조정
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #f8f9fa;
            }
            QScrollBar:vertical {
                background-color: #e9ecef;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #adb5bd;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6c757d;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # 스크롤 영역 내부의 위젯 생성
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                padding: 10px;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #dee2e6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #495057;
            }
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:pressed {
                background-color: #004085;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
            QLineEdit, QTextEdit {
                border: 2px solid #ced4da;
                border-radius: 4px;
                padding: 8px;
                background-color: #ffffff;
            }
            QLineEdit:focus, QTextEdit:focus {
                border-color: #007bff;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QSpinBox {
                border: 2px solid #ced4da;
                border-radius: 4px;
                padding: 4px;
            }
            QComboBox {
                border: 2px solid #ced4da;
                border-radius: 4px;
                padding: 4px;
                background-color: #ffffff;
            }
        """)
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(10)  # 위젯 간 간격 설정
        layout.setContentsMargins(15, 15, 15, 15)  # 여백 설정

        # 상단 대화 로그 (높이 줄임)
        self.chat_log = QTextEdit()
        self.chat_log.setMaximumHeight(100)  # 높이 제한
        self.chat_log.setReadOnly(True)
        self.chat_log.setStyleSheet("background-color: #f9f9f9; font-size: 11px; line-height: 1.2;")
        layout.addWidget(QLabel("📋 대화 로그"))
        layout.addWidget(self.chat_log)

        # input-keyword 입력창 추가 (검색어 옆에 붙일 주석)
        self.input_keyword = QLineEdit()
        self.input_keyword.setPlaceholderText("🔎 검색어 옆에 붙일 주석 (예: 최신정보, 추천)")
        self.input_keyword.setText(self.config.get("input_keyword", ""))
        self.input_keyword.textChanged.connect(self.save_config)
        layout.addWidget(self.input_keyword)

        # 콘텐츠 타입 선택 (소설/블로그)
        content_type_group = QGroupBox("📝 콘텐츠 타입 선택")
        content_type_layout = QHBoxLayout()
        
        self.content_type_combo = QComboBox()
        self.content_type_combo.addItems(['블로그', '소설'])
        self.content_type_combo.setCurrentText(self.config.get("content_type", "블로그"))
        self.content_type_combo.currentTextChanged.connect(self.on_content_type_changed)
        self.content_type_combo.currentTextChanged.connect(self.save_config)
        
        content_type_layout.addWidget(QLabel("콘텐츠 타입:"))
        content_type_layout.addWidget(self.content_type_combo)
        content_type_layout.addStretch()
        
        content_type_group.setLayout(content_type_layout)
        layout.addWidget(content_type_group)

        # 검색 엔진 선택 (Bing, Naver, Google)
        search_engine_group = QGroupBox("🔍 검색 엔진 선택")
        search_engine_layout = QHBoxLayout()
        
        self.search_engine_combo = QComboBox()
        self.search_engine_combo.addItems(['Bing', 'Naver', 'Google'])
        self.search_engine_combo.setCurrentText(self.config.get("search_engine", "Bing"))
        self.search_engine_combo.currentTextChanged.connect(self.save_config)
        
        search_engine_layout.addWidget(QLabel("검색 엔진:"))
        search_engine_layout.addWidget(self.search_engine_combo)
        search_engine_layout.addStretch()
        
        search_engine_group.setLayout(search_engine_layout)
        layout.addWidget(search_engine_group)

        # 이미지 프롬프트 요청사항 입력창 추가
        image_prompt_group = QGroupBox("🎨 이미지 프롬프트 요청사항")
        image_prompt_layout = QVBoxLayout()
        
        self.image_prompt_input = QTextEdit()
        self.image_prompt_input.setPlaceholderText("🎨 이미지 프롬프트 요청사항을 입력하세요 (예: 4K 고화질, 게임 스타일, 어두운 분위기, 전투 장면 등)")
        self.image_prompt_input.setMaximumHeight(80)
        self.image_prompt_input.setText(self.config.get("image_prompt_requirements", ""))
        self.image_prompt_input.textChanged.connect(self.save_config)
        
        # 기본값 복원 버튼 추가
        image_prompt_button_layout = QHBoxLayout()
        self.reset_image_prompt_button = QPushButton("🔄 이미지 프롬프트 기본값 복원")
        self.reset_image_prompt_button.clicked.connect(self.reset_image_prompt_to_default)
        self.reset_image_prompt_button.setToolTip("이미지 프롬프트를 기본값으로 되돌립니다")
        
        image_prompt_button_layout.addWidget(self.reset_image_prompt_button)
        image_prompt_button_layout.addStretch()
        
        image_prompt_layout.addWidget(self.image_prompt_input)
        image_prompt_layout.addLayout(image_prompt_button_layout)
        image_prompt_group.setLayout(image_prompt_layout)
        layout.addWidget(image_prompt_group)

        # 입력창 + 버튼
        input_layout = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("✍️ GPT에게 블로그 주제를 입력하세요...")
        self.input_box.returnPressed.connect(lambda: self.send_to_gpt(self.input_box.text().strip()))

        self.send_button = QPushButton("📤 전송")
        self.send_button.clicked.connect(lambda: self.send_to_gpt(self.input_box.text().strip()))

        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)

        # 멀티 키워드 입력창 (높이 줄임)
        self.keyword_input = QTextEdit()
        self.keyword_input.setPlaceholderText("🔍 쉼표로 구분된 키워드를 입력하세요 (예: 손흥민, 유로파, 토트넘)")
        self.keyword_input.setFixedHeight(50)  # 60에서 50으로 줄임
        layout.addWidget(self.keyword_input)

        # 멀티 검색 버튼들
        multi_button_layout = QHBoxLayout()
        
        self.multi_search_button = QPushButton("✅ 확인 및 멀티검색")
        self.multi_search_button.clicked.connect(self.handle_multi_keyword_search)
        
        self.pause_button = QPushButton("⏸️ 일시중지")
        self.pause_button.clicked.connect(self.pause_execution)
        self.pause_button.setEnabled(False)  # 초기에는 비활성화
        
        self.stop_button = QPushButton("🛑 강제종료")
        self.stop_button.clicked.connect(self.stop_execution)
        self.stop_button.setEnabled(False)  # 초기에는 비활성화
        
        # 구글 트렌드 수집 버튼 추가
        self.google_trends_button = QPushButton("📈 구글 트렌드 수집")
        self.google_trends_button.clicked.connect(self.collect_google_trends_to_keywords)
        
                # MySQL 핸들러 테스트 버튼 추가
        self.mysql_test_button = QPushButton("🗄️ MySQL 테스트")
        self.mysql_test_button.clicked.connect(self.test_mysql_handler)

        # 광고 링크 입력란 추가
        ad_link_group = QGroupBox("🎁 광고/프로모션 링크")
        ad_link_layout = QVBoxLayout()
        
        self.ad_link_input = QLineEdit()
        self.ad_link_input.setPlaceholderText("Microsoft Rewards 링크 (예: https://rewards.microsoft.com/...)")
        self.ad_link_input.setToolTip("Microsoft Rewards나 기타 프로모션 링크를 입력하세요")
        self.ad_link_input.textChanged.connect(self.on_ad_link_changed)
        
        ad_link_layout.addWidget(self.ad_link_input)
        ad_link_group.setLayout(ad_link_layout)
        
        # 광고 링크를 메인 레이아웃에 추가
        layout.addWidget(ad_link_group)

        multi_button_layout.addWidget(self.multi_search_button)
        multi_button_layout.addWidget(self.pause_button)
        multi_button_layout.addWidget(self.stop_button)
        multi_button_layout.addWidget(self.google_trends_button)
        multi_button_layout.addWidget(self.mysql_test_button)
        
        layout.addLayout(multi_button_layout)
        
        # 설정 옵션들
        settings_group = QGroupBox("설정 옵션")
        settings_layout = QGridLayout()
        
        # 티스토리 업로드
        self.tistory_checkbox = QCheckBox('티스토리 업로드')
        self.tistory_checkbox.setChecked(self.config.get("tistory_enabled", False))
        self.tistory_checkbox.stateChanged.connect(self.save_config)
        settings_layout.addWidget(self.tistory_checkbox, 0, 0)
        
        # 네이버 블로그 업로드
        self.naver_checkbox = QCheckBox('네이버 블로그 업로드')
        self.naver_checkbox.setChecked(self.config.get("naver_enabled", False))
        self.naver_checkbox.stateChanged.connect(self.save_config)
        settings_layout.addWidget(self.naver_checkbox, 0, 1)
        
        # 이미지 소스 선택
        image_source_layout = QHBoxLayout()
        image_source_layout.addWidget(QLabel('이미지 소스:'))
        self.image_source_combo = QComboBox()
        self.image_source_combo.addItems(['none', 'bing', 'sora', 'bing_sora', 'pinterest', 'coupang'])
        self.image_source_combo.setCurrentText(self.config.get("image_source", "bing"))
        self.image_source_combo.currentTextChanged.connect(self.save_config)
        image_source_layout.addWidget(self.image_source_combo)
        settings_layout.addLayout(image_source_layout, 1, 0, 1, 2)
        
        # Bing 이미지 개수 설정
        bing_count_layout = QHBoxLayout()
        bing_count_layout.addWidget(QLabel('Bing 이미지 개수:'))
        self.bing_image_count_spinbox = QSpinBox()
        self.bing_image_count_spinbox.setRange(1, 10)
        self.bing_image_count_spinbox.setValue(self.config.get("bing_image_count", 3))
        self.bing_image_count_spinbox.setSuffix(" 장")
        self.bing_image_count_spinbox.valueChanged.connect(self.save_config)
        bing_count_layout.addWidget(self.bing_image_count_spinbox)
        settings_layout.addLayout(bing_count_layout, 2, 0, 1, 2)
        
        # GIF 유사도 설정
        gif_similarity_layout = QHBoxLayout()
        gif_similarity_layout.addWidget(QLabel('GIF 유사도:'))
        self.gif_similarity_spinbox = QSpinBox()
        self.gif_similarity_spinbox.setRange(10, 100)
        self.gif_similarity_spinbox.setValue(self.config.get("gif_similarity", 50))
        self.gif_similarity_spinbox.setSuffix("%")
        self.gif_similarity_spinbox.setToolTip("GIF 생성 시 유사도 임계값 (높을수록 더 유사한 이미지만 선택)")
        self.gif_similarity_spinbox.valueChanged.connect(self.save_config)
        gif_similarity_layout.addWidget(self.gif_similarity_spinbox)
        settings_layout.addLayout(gif_similarity_layout, 3, 0, 1, 2)
        
        # GIF 포함률 설정
        gif_inclusion_layout = QHBoxLayout()
        gif_inclusion_layout.addWidget(QLabel('GIF 포함률:'))
        self.gif_inclusion_spinbox = QSpinBox()
        self.gif_inclusion_spinbox.setRange(10, 100)
        self.gif_inclusion_spinbox.setValue(self.config.get("gif_inclusion", 50))
        self.gif_inclusion_spinbox.setSuffix("%")
        self.gif_inclusion_spinbox.setToolTip("GIF가 최종 결과에 포함될 확률 (높을수록 GIF 사용 빈도 증가)")
        self.gif_inclusion_spinbox.valueChanged.connect(self.save_config)
        gif_inclusion_layout.addWidget(self.gif_inclusion_spinbox)
        settings_layout.addLayout(gif_inclusion_layout, 4, 0, 1, 2)

        # 단어 포함률 임계값 설정
        word_inclusion_layout = QHBoxLayout()
        word_inclusion_layout.addWidget(QLabel('단어 포함률 임계값:'))
        self.word_inclusion_spinbox = QSpinBox()
        self.word_inclusion_spinbox.setRange(10, 100)
        self.word_inclusion_spinbox.setValue(self.config.get("word_inclusion_threshold", 30))
        self.word_inclusion_spinbox.setSuffix("%")
        self.word_inclusion_spinbox.setToolTip("단어 포함률이 이 값 이상일 때만 유사도 비교 실행 (낮을수록 더 많은 파일 검사)")
        self.word_inclusion_spinbox.valueChanged.connect(self.save_config)
        word_inclusion_layout.addWidget(self.word_inclusion_spinbox)
        settings_layout.addLayout(word_inclusion_layout, 5, 0, 1, 2)

        # 사용 모델 선택
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel('GPT 모델:'))
        self.chat_model_combo = QComboBox()
        self.chat_model_combo.addItems(['gpt-5-mini', 'gpt-4o-mini'])
        self.chat_model_combo.setCurrentText(self.config.get("chat_model", "gpt-5-mini"))
        self.chat_model_combo.currentTextChanged.connect(self.save_config)
        model_layout.addWidget(self.chat_model_combo)
        settings_layout.addLayout(model_layout, 5, 1)
        
        # 사이트 업로드
        self.site_upload_checkbox = QCheckBox('사이트 업로드')
        self.site_upload_checkbox.setChecked(True)
        settings_layout.addWidget(self.site_upload_checkbox, 6, 0)
        
        # bo_table 선택 (게시판 테이블)
        bo_table_layout = QHBoxLayout()
        bo_table_layout.addWidget(QLabel('게시판 테이블:'))
        self.bo_table_combo = QComboBox()
        self.bo_table_combo.addItems(['free', 'notice', 'qna', 'gallery', 'review', 'news', 'blog'])
        self.bo_table_combo.setCurrentText(self.config.get("bo_table", "free"))
        self.bo_table_combo.currentTextChanged.connect(self.save_config)
        bo_table_layout.addWidget(self.bo_table_combo)
        settings_layout.addLayout(bo_table_layout, 7, 0, 1, 2)
        
        # ca_name 선택 (카테고리) - prompt_functions.py에서 가져오기
        ca_name_layout = QHBoxLayout()
        ca_name_layout.addWidget(QLabel('카테고리:'))
        self.ca_name_combo = QComboBox()
        
        # prompt_functions.py에서 카테고리 목록 가져오기
        try:
            from prompt_functions import CATEGORY_LIST
            ca_names = [cat["ca_name"] for cat in CATEGORY_LIST]
            self.ca_name_combo.addItems(ca_names)
        except ImportError:
            # 기본 카테고리 (fallback)
            self.ca_name_combo.addItems(['일반', '공지', '질문', '갤러리', '리뷰', '뉴스', '정보', '팁'])
        
        self.ca_name_combo.setCurrentText(self.config.get("ca_name", "일반"))
        self.ca_name_combo.currentTextChanged.connect(self.save_config)
        ca_name_layout.addWidget(self.ca_name_combo)
        settings_layout.addLayout(ca_name_layout, 8, 0, 1, 2)
        
        # 랜덤 확률 설정
        self.use_random_probability_checkbox = QCheckBox('랜덤 확률 적용')
        self.use_random_probability_checkbox.setChecked(self.config.get("use_random_probability", False))
        self.use_random_probability_checkbox.stateChanged.connect(self.save_config)
        settings_layout.addWidget(self.use_random_probability_checkbox, 6, 1)
        
        # 랜덤 확률 값 설정
        random_prob_layout = QHBoxLayout()
        random_prob_layout.addWidget(QLabel('확률:'))
        self.random_probability_spinbox = QSpinBox()
        self.random_probability_spinbox.setRange(1, 100)
        self.random_probability_spinbox.setValue(self.config.get("random_probability", 85))
        self.random_probability_spinbox.setSuffix("%")
        self.random_probability_spinbox.valueChanged.connect(self.save_config)
        random_prob_layout.addWidget(self.random_probability_spinbox)
        settings_layout.addLayout(random_prob_layout, 9, 0, 1, 2)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # 구글 트렌드 자동화 그룹 (간소화)
        trends_auto_group = QGroupBox("🔄 구글 트렌드 자동 수집")
        trends_auto_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #ccc;
                border-radius: 5px;
                margin-top: 5px;
                padding-top: 5px;
            }
        """)
        
        trends_auto_layout = QGridLayout()
        
        # 자동화 활성화 체크박스
        self.auto_trends_checkbox = QCheckBox("🔄 자동 트렌드 수집 활성화")
        # 항상 기본 표시 상태는 체크 해제
        self.auto_trends_checkbox.setChecked(False)
        self.auto_trends_checkbox.stateChanged.connect(self.toggle_auto_trends)
        trends_auto_layout.addWidget(self.auto_trends_checkbox, 0, 0, 1, 2)
        
        # 자동 멀티검색 체크박스 추가
        self.auto_multi_search_checkbox = QCheckBox("🚀 자동 멀티검색 활성화 (수집 완료 후 자동 실행)")
        self.auto_multi_search_checkbox.setChecked(self.config.get("auto_multi_search_enabled", True))
        self.auto_multi_search_checkbox.stateChanged.connect(self.save_config)
        trends_auto_layout.addWidget(self.auto_multi_search_checkbox, 1, 0, 1, 2)
        
        # 수집 간격 설정
        interval_label = QLabel("⏰ 수집 간격:")
        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(1, 1440)  # 1분 ~ 24시간
        self.interval_spinbox.setValue(self.config.get("trends_interval", 60))
        self.interval_spinbox.setSuffix(" 분")
        self.interval_spinbox.valueChanged.connect(self.update_trends_interval)
        trends_auto_layout.addWidget(interval_label, 2, 0)
        trends_auto_layout.addWidget(self.interval_spinbox, 2, 1)

        # 빠른 간격 설정 버튼들
        quick_interval_layout = QHBoxLayout()
        quick_label = QLabel("빠른 설정:")
        quick_interval_layout.addWidget(quick_label)
        btn_1m = QPushButton("1분")
        btn_3m = QPushButton("3분")
        btn_5m = QPushButton("5분")
        btn_15m = QPushButton("15분")
        btn_30m = QPushButton("30분")
        btn_1m.setToolTip("수집 간격을 1분으로 설정")
        btn_3m.setToolTip("수집 간격을 3분으로 설정")
        btn_5m.setToolTip("수집 간격을 5분으로 설정")
        btn_15m.setToolTip("수집 간격을 15분으로 설정")
        btn_30m.setToolTip("수집 간격을 30분으로 설정")
        btn_1m.clicked.connect(lambda: self.interval_spinbox.setValue(1))
        btn_3m.clicked.connect(lambda: self.interval_spinbox.setValue(3))
        btn_5m.clicked.connect(lambda: self.interval_spinbox.setValue(5))
        btn_15m.clicked.connect(lambda: self.interval_spinbox.setValue(15))
        btn_30m.clicked.connect(lambda: self.interval_spinbox.setValue(30))
        quick_interval_layout.addWidget(btn_1m)
        quick_interval_layout.addWidget(btn_3m)
        quick_interval_layout.addWidget(btn_5m)
        quick_interval_layout.addWidget(btn_15m)
        quick_interval_layout.addWidget(btn_30m)
        quick_interval_layout.addStretch()
        trends_auto_layout.addLayout(quick_interval_layout, 3, 0, 1, 2)

        # 게시물 간 간격 설정 (1/3/5/15/30분)
        post_interval_label = QLabel("🕓 게시물 간 간격:")
        self.post_interval_combo = QComboBox()
        self.post_interval_combo.addItems(["1", "3", "5", "15", "30"])
        try:
            self.post_interval_combo.setCurrentText(str(self.config.get("post_interval_minutes", 1)))
        except Exception:
            self.post_interval_combo.setCurrentText("1")
        self.post_interval_combo.currentTextChanged.connect(self.save_config)
        trends_auto_layout.addWidget(post_interval_label, 4, 0)
        trends_auto_layout.addWidget(self.post_interval_combo, 4, 1)
        
        # 부하 제어 옵션
        load_control_label = QLabel("⚡ 부하 제어:")
        self.load_control_checkbox = QCheckBox("🛡️ 부하 제어 활성화 (권장)")
        self.load_control_checkbox.setChecked(self.config.get("load_control_enabled", True))
        self.load_control_checkbox.stateChanged.connect(self.save_config)
        trends_auto_layout.addWidget(load_control_label, 5, 0)
        trends_auto_layout.addWidget(self.load_control_checkbox, 5, 1)
        
        # 다음 수집 시간 표시
        self.next_collection_label = QLabel("⏳ 다음 수집: --:--")
        self.next_collection_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        trends_auto_layout.addWidget(self.next_collection_label, 6, 0, 1, 2)
        
        # 자동화 상태 표시
        self.auto_status_label = QLabel("상태: 대기 중")
        self.auto_status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
        trends_auto_layout.addWidget(self.auto_status_label, 7, 0, 1, 2)
        
        trends_auto_group.setLayout(trends_auto_layout)
        layout.addWidget(trends_auto_group)
        
        # 쿠팡 상품 자동 수집 그룹
        coupang_auto_group = QGroupBox("🛒 쿠팡 상품 자동 수집")
        coupang_auto_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #ccc;
                border-radius: 5px;
                margin-top: 5px;
                padding-top: 5px;
            }
        """)
        
        coupang_auto_layout = QGridLayout()
        
        # 자동화 활성화 체크박스
        self.auto_coupang_checkbox = QCheckBox("🔄 자동 상품 수집 활성화")
        self.auto_coupang_checkbox.setChecked(False)
        self.auto_coupang_checkbox.stateChanged.connect(self.toggle_auto_coupang)
        coupang_auto_layout.addWidget(self.auto_coupang_checkbox, 0, 0, 1, 2)
        
        # 수집 간격 설정
        coupang_interval_label = QLabel("⏰ 수집 간격:")
        self.coupang_interval_spinbox = QSpinBox()
        self.coupang_interval_spinbox.setRange(1, 1440)  # 1분 ~ 24시간
        self.coupang_interval_spinbox.setValue(self.config.get("coupang_interval", 60))
        self.coupang_interval_spinbox.setSuffix(" 분")
        self.coupang_interval_spinbox.valueChanged.connect(self.update_coupang_interval)
        coupang_auto_layout.addWidget(coupang_interval_label, 1, 0)
        coupang_auto_layout.addWidget(self.coupang_interval_spinbox, 1, 1)
        
        # 빠른 간격 설정 버튼들
        coupang_quick_interval_layout = QHBoxLayout()
        coupang_quick_label = QLabel("빠른 설정:")
        coupang_quick_interval_layout.addWidget(coupang_quick_label)
        coupang_btn_1m = QPushButton("1분")
        coupang_btn_3m = QPushButton("3분")
        coupang_btn_5m = QPushButton("5분")
        coupang_btn_15m = QPushButton("15분")
        coupang_btn_30m = QPushButton("30분")
        coupang_btn_1m.setToolTip("수집 간격을 1분으로 설정")
        coupang_btn_3m.setToolTip("수집 간격을 3분으로 설정")
        coupang_btn_5m.setToolTip("수집 간격을 5분으로 설정")
        coupang_btn_15m.setToolTip("수집 간격을 15분으로 설정")
        coupang_btn_30m.setToolTip("수집 간격을 30분으로 설정")
        coupang_btn_1m.clicked.connect(lambda: self.coupang_interval_spinbox.setValue(1))
        coupang_btn_3m.clicked.connect(lambda: self.coupang_interval_spinbox.setValue(3))
        coupang_btn_5m.clicked.connect(lambda: self.coupang_interval_spinbox.setValue(5))
        coupang_btn_15m.clicked.connect(lambda: self.coupang_interval_spinbox.setValue(15))
        coupang_btn_30m.clicked.connect(lambda: self.coupang_interval_spinbox.setValue(30))
        coupang_quick_interval_layout.addWidget(coupang_btn_1m)
        coupang_quick_interval_layout.addWidget(coupang_btn_3m)
        coupang_quick_interval_layout.addWidget(coupang_btn_5m)
        coupang_quick_interval_layout.addWidget(coupang_btn_15m)
        coupang_quick_interval_layout.addWidget(coupang_btn_30m)
        coupang_quick_interval_layout.addStretch()
        coupang_auto_layout.addLayout(coupang_quick_interval_layout, 2, 0, 1, 2)
        
        # 쿠팡 상품 이미지 사용
        self.coupang_image_checkbox = QCheckBox("🖼️ 쿠팡 상품 이미지 사용")
        self.coupang_image_checkbox.setChecked(self.config.get("coupang_image_enabled", False))
        self.coupang_image_checkbox.stateChanged.connect(self.save_config)
        self.coupang_image_checkbox.setToolTip("블로그 글에 쿠팡 상품 이미지를 포함합니다")
        coupang_auto_layout.addWidget(self.coupang_image_checkbox, 3, 0, 1, 2)
        
        # 쿠팡 상품 링크 사용
        self.coupang_link_checkbox = QCheckBox("🔗 쿠팡 상품 링크 사용")
        self.coupang_link_checkbox.setChecked(self.config.get("coupang_link_enabled", False))
        self.coupang_link_checkbox.stateChanged.connect(self.save_config)
        self.coupang_link_checkbox.setToolTip("상품 이미지에 상품 링크를 연결합니다")
        coupang_auto_layout.addWidget(self.coupang_link_checkbox, 4, 0, 1, 2)
        
        # 다음 수집 시간 표시
        self.next_coupang_collection_label = QLabel("⏳ 다음 수집: --:--")
        self.next_coupang_collection_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        coupang_auto_layout.addWidget(self.next_coupang_collection_label, 5, 0, 1, 2)
        
        # 자동화 상태 표시
        self.coupang_auto_status_label = QLabel("상태: 대기 중")
        self.coupang_auto_status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
        coupang_auto_layout.addWidget(self.coupang_auto_status_label, 6, 0, 1, 2)
        
        coupang_auto_group.setLayout(coupang_auto_layout)
        layout.addWidget(coupang_auto_group)
        
        # 스크롤 영역에 위젯 설정
        scroll_area.setWidget(scroll_widget)
        
        # 메인 레이아웃에 스크롤 영역 추가
        main_layout.addWidget(scroll_area)
        
        # 메인 레이아웃을 위젯에 설정
        self.setLayout(main_layout)
        
        self.chat_log.append("🚀 최적화된 버전이 로드되었습니다!\n")
        self.chat_log.append("모듈들을 비동기로 로드 중입니다...\n")
        print("🚀 최적화된 버전이 로드되었습니다!")
        print("모듈들을 비동기로 로드 중입니다...")

    def load_coupang_selected_data(self):
        """쿠팡 선택 상품 JSON 파일을 읽는 함수"""
        try:
            json_path = self.config.get("coupang_selected_json_path", 
                r"E:\Gif\www\참소식.com\gnuboard5.5.8.3.2\theme\nbBasic\parts\data\coupang-selected.json")
            
            if not os.path.exists(json_path):
                print(f"⚠️ 쿠팡 선택 상품 파일을 찾을 수 없습니다: {json_path}")
                return None
            
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # selected 배열이 있고 비어있지 않은지 확인
            if not data.get("selected") or len(data["selected"]) == 0:
                print(f"⚠️ 쿠팡 선택 상품이 없습니다 (total: {data.get('total', 0)})")
                return None
            
            print(f"✅ 쿠팡 선택 상품 데이터 로드 완료: {len(data['selected'])}개")
            return data
            
        except FileNotFoundError:
            print(f"⚠️ 쿠팡 선택 상품 파일을 찾을 수 없습니다: {json_path}")
            return None
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON 파일 파싱 오류: {e}")
            return None
        except Exception as e:
            print(f"⚠️ 쿠팡 선택 상품 데이터 로드 실패: {e}")
            return None

    def get_random_coupang_product(self):
        """쿠팡 상품 중 랜덤으로 하나를 선택하는 함수 (자동 수집된 상품 우선 사용)"""
        try:
            import random
            
            # 1. 자동 수집된 상품 파일 우선 확인
            products_json_path = self.config.get("coupang_products_json_path",
                r"E:\Gif\www\참소식.com\gnuboard5.5.8.3.2\theme\nbBasic\parts\data\coupang-products.json")
            
            if os.path.exists(products_json_path):
                try:
                    with open(products_json_path, 'r', encoding='utf-8') as f:
                        products_data = json.load(f)
                    
                    # JSON 구조에 따라 상품 정보 추출
                    collected_products = []
                    if isinstance(products_data, list):
                        collected_products = products_data
                    elif isinstance(products_data, dict):
                        if "products" in products_data:
                            collected_products = products_data["products"]
                        elif "data" in products_data:
                            if isinstance(products_data["data"], list):
                                collected_products = products_data["data"]
                            elif isinstance(products_data["data"], dict) and "products" in products_data["data"]:
                                collected_products = products_data["data"]["products"]
                        elif "selected" in products_data:
                            collected_products = products_data["selected"]
                        elif "items" in products_data:
                            collected_products = products_data["items"]
                        else:
                            for key, value in products_data.items():
                                if isinstance(value, list) and len(value) > 0:
                                    collected_products = value
                                    break
                    
                    if collected_products and len(collected_products) > 0:
                        product = random.choice(collected_products)
                        print(f"✅ 자동 수집된 쿠팡 상품 선택: {product.get('name', product.get('title', '이름 없음'))}")
                        return product
                except Exception as e:
                    print(f"⚠️ 자동 수집 상품 파일 읽기 실패: {e}")
            
            # 2. 자동 수집 상품이 없으면 선택 상품 파일 확인
            data = self.load_coupang_selected_data()
            if data and data.get("selected"):
                selected_products = data["selected"]
                if len(selected_products) > 0:
                    product = random.choice(selected_products)
                    print(f"✅ 쿠팡 선택 상품 선택: {product.get('name', '이름 없음')}")
                    return product
            
            return None
        except Exception as e:
            print(f"⚠️ 쿠팡 상품 선택 실패: {e}")
            return None

    def create_coupang_ad_image_html(self, product, use_link=True):
        """쿠팡 상품 광고 이미지 HTML 생성 (이미지에 상품 링크 연결)"""
        try:
            if not product:
                return ""
            
            # 상품 정보 추출 (JSON 구조에 따라 조정 필요)
            product_name = product.get("name", product.get("title", "상품명"))
            product_url = product.get("url", product.get("link", product.get("product_url", "")))
            product_image = product.get("image", product.get("image_url", product.get("thumbnail", "")))
            
            # 링크 사용 여부 확인
            if use_link and not product_url:
                print(f"⚠️ 쿠팡 상품 URL이 없습니다: {product_name}")
                # 링크가 없어도 이미지만 표시할 수 있도록 계속 진행
            
            # 이미지가 없으면 기본 이미지 사용 또는 텍스트만
            if not product_image:
                # 이미지 없이 텍스트만 생성
                ad_html = f'<div style="margin:20px 0;padding:15px;background:#f8f9fa;border-radius:8px;text-align:center;">'
                if use_link and product_url:
                    ad_html += f'<a href="{product_url}" target="_blank" rel="noopener" style="text-decoration:none;color:#333;">'
                    ad_html += f'<h3 style="margin:0;color:#007bff;">{product_name}</h3>'
                    ad_html += f'<p style="margin:10px 0;color:#666;">상품 보러가기 →</p>'
                    ad_html += f'</a>'
                else:
                    ad_html += f'<h3 style="margin:0;color:#007bff;">{product_name}</h3>'
                ad_html += f'</div>'
            else:
                # 이미지 포함
                ad_html = f'<div style="margin:20px 0;text-align:center;">'
                if use_link and product_url:
                    # 링크 사용: 이미지를 링크로 감싸기
                    ad_html += f'<a href="{product_url}" target="_blank" rel="noopener" style="text-decoration:none;display:inline-block;">'
                    ad_html += f'<img src="{product_image}" alt="{product_name}" style="width:100%;max-width:600px;height:auto;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);cursor:pointer;" />'
                    ad_html += f'<p style="margin-top:10px;color:#007bff;font-weight:bold;">{product_name}</p>'
                    ad_html += f'</a>'
                else:
                    # 링크 미사용: 이미지만 표시
                    ad_html += f'<img src="{product_image}" alt="{product_name}" style="width:100%;max-width:600px;height:auto;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);" />'
                    ad_html += f'<p style="margin-top:10px;color:#007bff;font-weight:bold;">{product_name}</p>'
                ad_html += f'</div>'
            
            return ad_html
            
        except Exception as e:
            print(f"⚠️ 쿠팡 광고 이미지 HTML 생성 실패: {e}")
            return ""

    def sanitize_and_fix_links(self, html: str, coupang_product: dict = None) -> str:
        """본문 내 잘못된/공백 앵커를 정리하고 검색 링크를 표준화 (Bing, Naver, Google 지원), 쿠팡 이미지에 링크 추가"""
        try:
            import re
            from urllib.parse import quote

            fixed = html or ""

            # 1) 비표준 bing 링크를 표준 형태로 교체
            #    href="bing.com?search=..." 또는 href="https://bing.com?search=..."
            fixed = re.sub(r'href=["\"](?:https?://)?bing\.com\?search=([^"]+)["\"]',
                           lambda m: f'href="https://www.bing.com/search?q={quote(m.group(1))}&sendquery=1&FORM=SCCODX&rh=B0D80A4F&ref=rafsrchae"',
                           fixed)
            
            # 2) 비표준 naver 링크를 표준 형태로 교체
            fixed = re.sub(r'href=["\"](?:https?://)?(?:search\.)?naver\.com\?search=([^"]+)["\"]',
                           lambda m: f'href="https://search.naver.com/search.naver?query={quote(m.group(1))}"',
                           fixed)
            
            # 3) 비표준 google 링크를 표준 형태로 교체
            fixed = re.sub(r'href=["\"](?:https?://)?(?:www\.)?google\.com\?search=([^"]+)["\"]',
                           lambda m: f'href="https://www.google.com/search?q={quote(m.group(1))}"',
                           fixed)

            # 2) 빈 앵커 제거: <a ...></a>
            fixed = re.sub(r'<a\b[^>]*>\s*</a>', '', fixed)

            # 3) 쿠팡 상품 이미지에 링크 추가 (Bing 이미지, Sora 이미지처럼)
            if coupang_product:
                coupang_link_enabled = self.config.get("coupang_link_enabled", False)
                if coupang_link_enabled:
                    product_url = coupang_product.get("url", coupang_product.get("link", coupang_product.get("product_url", "")))
                    product_image = coupang_product.get("image", coupang_product.get("image_url", coupang_product.get("thumbnail", "")))
                    
                    if product_url and product_image:
                        # 본문 내 쿠팡 상품 이미지를 찾아서 링크로 감싸기
                        # 이미지를 링크로 감싸지 않은 img 태그만 처리
                        def wrap_coupang_image(match: re.Match) -> str:
                            full_match = match.group(0)
                            img_tag = match.group(1)
                            
                            # 이미 링크로 감싸져 있는지 확인 (앞 100자 확인)
                            before_text = fixed[max(0, match.start()-100):match.start()]
                            if '<a' in before_text and '</a>' not in before_text[:before_text.rfind('<a')]:
                                # 이미 링크 안에 있음
                                return full_match
                            
                            # 쿠팡 이미지 URL이 포함된 img 태그인지 확인
                            if product_image in img_tag:
                                # 이미지를 링크로 감싸기
                                return f'<a href="{product_url}" target="_blank" rel="noopener">{img_tag}</a>'
                            return full_match
                        
                        # 쿠팡 이미지 URL이 포함된 img 태그 찾기 (이미 링크로 감싸지 않은 것만)
                        # 패턴: <img ... src="...쿠팡이미지URL..." ...>
                        escaped_image_url = re.escape(product_image)
                        fixed = re.sub(
                            r'(<img\s+[^>]*src=["\'][^"\']*' + escaped_image_url + r'[^"\']*["\'][^>]*>)',
                            wrap_coupang_image,
                            fixed,
                            flags=re.IGNORECASE
                        )

            # 4) target, rel 보강: 없는 경우 추가
            def add_target_rel(match: re.Match) -> str:
                tag = match.group(0)
                if 'target=' not in tag:
                    tag = tag[:-1] + ' target="_blank" rel="noopener">'
                elif 'rel=' not in tag:
                    tag = tag[:-1] + ' rel="noopener">'
                return tag

            fixed = re.sub(r'<a\b[^>]*?>', add_target_rel, fixed)

            return fixed
        except Exception as e:
            print(f"⚠️ 링크 수정 중 오류: {e}")
            return html

    def sleep_with_controls(self, minutes: int = 1):
        """게시물 간 대기시간 동안 일시정지/중지 상태를 반영하여 대기.
        - minutes: 분 단위 대기시간
        """
        try:
            total_ms = max(0, int(minutes) * 60 * 1000)
        except Exception:
            total_ms = 60 * 1000
        step_ms = 200  # 0.2초 단위로 체크하여 UI 반응성 확보
        elapsed = 0
        while elapsed < total_ms:
            if self.should_stop:
                break
            if self.is_paused:
                time.sleep(0.1)
                continue
            time.sleep(step_ms / 1000.0)
            elapsed += step_ms

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self.config.update(loaded_config)
                print("📋 설정 로드 완료")
                if hasattr(self, 'chat_log'):
                    self.chat_log.append("📋 설정 로드 완료\n")
                
                # UI 요소에 설정 적용
                if hasattr(self, 'ad_link_input'):
                    self.ad_link_input.setText(self.config.get("ad_link", ""))
                if hasattr(self, 'image_prompt_input'):
                    # 이미지 프롬프트가 비어있거나 기본값이 아닌 경우 기본값으로 설정
                    current_prompt = self.config.get("image_prompt_requirements", "")
                    content_type = self.config.get("content_type", "블로그")
                    
                    if not current_prompt or current_prompt == "4K 고화질, 디테일하고 자세한 이미지":
                        # 기본값으로 설정
                        try:
                            from prompt_templates import get_default_image_prompt_requirements, get_default_novel_image_prompt_requirements
                            
                            if content_type == "소설":
                                default_prompt = get_default_novel_image_prompt_requirements()
                            else:
                                default_prompt = get_default_image_prompt_requirements()
                            
                            self.image_prompt_input.setPlainText(default_prompt)
                            self.config["image_prompt_requirements"] = default_prompt
                            print(f"🔄 초기 로드 시 이미지 프롬프트를 기본값으로 설정: {default_prompt}")
                        except ImportError:
                            # prompt_templates 모듈이 없을 경우 하드코딩된 기본값 사용
                            if content_type == "소설":
                                default_prompt = "판타지 스타일, 로맨틱 분위기, 4K 고화질, 상세한 묘사, 감정적 표현"
                            else:
                                default_prompt = "4K 고화질, 디테일하고 자세한 이미지, 현실적인 스타일"
                            
                            self.image_prompt_input.setPlainText(default_prompt)
                            self.config["image_prompt_requirements"] = default_prompt
                            print(f"🔄 초기 로드 시 이미지 프롬프트를 기본값으로 설정: {default_prompt}")
                    else:
                        # 기존 설정값 사용
                        self.image_prompt_input.setPlainText(current_prompt)
                if hasattr(self, 'use_random_probability_checkbox'):
                    self.use_random_probability_checkbox.setChecked(self.config.get("use_random_probability", False))
                if hasattr(self, 'random_probability_spinbox'):
                    self.random_probability_spinbox.setValue(self.config.get("random_probability", 85))
                if hasattr(self, 'bing_image_count_spinbox'):
                    self.bing_image_count_spinbox.setValue(self.config.get("bing_image_count", 3))
                if hasattr(self, 'gif_similarity_spinbox'):
                    self.gif_similarity_spinbox.setValue(self.config.get("gif_similarity", 50))
                if hasattr(self, 'gif_inclusion_spinbox'):
                    self.gif_inclusion_spinbox.setValue(self.config.get("gif_inclusion", 50))
                if hasattr(self, 'word_inclusion_spinbox'):
                    self.word_inclusion_spinbox.setValue(self.config.get("word_inclusion_threshold", 30))
                if hasattr(self, 'load_control_checkbox'):
                    self.load_control_checkbox.setChecked(self.config.get("load_control_enabled", True))
                if hasattr(self, 'post_interval_combo'):
                    try:
                        self.post_interval_combo.setCurrentText(str(self.config.get("post_interval_minutes", 1)))
                    except Exception:
                        self.post_interval_combo.setCurrentText("1")
                if hasattr(self, 'bo_table_combo'):
                    self.bo_table_combo.setCurrentText(self.config.get("bo_table", "free"))
                if hasattr(self, 'ca_name_combo'):
                    self.ca_name_combo.setCurrentText(self.config.get("ca_name", "일반"))
                if hasattr(self, 'content_type_combo'):
                    self.content_type_combo.setCurrentText(self.config.get("content_type", "블로그"))
            if hasattr(self, 'chat_model_combo'):
                self.chat_model_combo.setCurrentText(self.config.get("chat_model", "gpt-5-mini"))
            if hasattr(self, 'search_engine_combo'):
                search_engine = self.config.get("search_engine", "bing")
                # 대소문자 구분 없이 매칭
                search_engine_lower = search_engine.lower()
                if search_engine_lower == "naver":
                    self.search_engine_combo.setCurrentText("Naver")
                elif search_engine_lower == "google":
                    self.search_engine_combo.setCurrentText("Google")
                else:
                    self.search_engine_combo.setCurrentText("Bing")
            if hasattr(self, 'coupang_image_checkbox'):
                self.coupang_image_checkbox.setChecked(self.config.get("coupang_image_enabled", False))
            if hasattr(self, 'coupang_link_checkbox'):
                self.coupang_link_checkbox.setChecked(self.config.get("coupang_link_enabled", False))
        except Exception as e:
            print(f"❌ 설정 로드 실패: {e}")
            if hasattr(self, 'chat_log'):
                self.chat_log.append(f"❌ 설정 로드 실패: {e}\n")

    def save_config(self):
        try:
            # UI 요소에서 설정 값 가져오기
            self.config["tistory_enabled"] = self.tistory_checkbox.isChecked()
            self.config["naver_enabled"] = self.naver_checkbox.isChecked()
            self.config["image_source"] = self.image_source_combo.currentText()
            self.config["input_keyword"] = self.input_keyword.text()
            self.config["image_prompt_requirements"] = self.image_prompt_input.toPlainText().strip()
            self.config["content_type"] = self.content_type_combo.currentText()
            # 자동수집은 저장하지 않음: 항상 False 유지
            self.config["auto_trends_enabled"] = False
            self.config["trends_interval"] = self.interval_spinbox.value()
            self.config["use_random_probability"] = self.use_random_probability_checkbox.isChecked()
            self.config["random_probability"] = self.random_probability_spinbox.value()
            self.config["bing_image_count"] = self.bing_image_count_spinbox.value()
            self.config["gif_similarity"] = self.gif_similarity_spinbox.value()
            self.config["gif_inclusion"] = self.gif_inclusion_spinbox.value()
            self.config["word_inclusion_threshold"] = self.word_inclusion_spinbox.value()
            self.config["load_control_enabled"] = self.load_control_checkbox.isChecked()
            self.config["auto_multi_search_enabled"] = self.auto_multi_search_checkbox.isChecked()  # 자동 멀티검색 설정 추가
            if hasattr(self, 'post_interval_combo'):
                try:
                    self.config["post_interval_minutes"] = int(self.post_interval_combo.currentText())
                except Exception:
                    self.config["post_interval_minutes"] = 1
            if hasattr(self, 'chat_model_combo'):
                self.config["chat_model"] = self.chat_model_combo.currentText()
            
            # bo_table과 ca_name 설정 추가
            if hasattr(self, 'bo_table_combo'):
                self.config["bo_table"] = self.bo_table_combo.currentText()
            if hasattr(self, 'ca_name_combo'):
                self.config["ca_name"] = self.ca_name_combo.currentText()
            
            # 쿠팡 상품 이미지 및 링크 설정 추가
            if hasattr(self, 'coupang_image_checkbox'):
                self.config["coupang_image_enabled"] = self.coupang_image_checkbox.isChecked()
            if hasattr(self, 'coupang_link_checkbox'):
                self.config["coupang_link_enabled"] = self.coupang_link_checkbox.isChecked()
            if hasattr(self, 'coupang_interval_spinbox'):
                self.config["coupang_interval"] = self.coupang_interval_spinbox.value()
            
            # 검색 엔진 설정 추가
            if hasattr(self, 'search_engine_combo'):
                self.config["search_engine"] = self.search_engine_combo.currentText().lower()
            
            # 설정 파일에 저장
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            print("✅ 설정 저장 완료")
        except Exception as e:
            print(f"❌ 설정 저장 실패: {e}")
            if hasattr(self, 'chat_log'):
                self.chat_log.append(f"❌ 설정 저장 실패: {e}\n")

    def handle_multi_keyword_search(self):
        keywords_text = self.keyword_input.toPlainText().strip()
        if not keywords_text:
            self.chat_log.append("❌ 키워드를 입력해주세요.\n")
            print("❌ 키워드를 입력해주세요.")
            return
        
        # 쉼표/개행/세미콜론 등 다양한 구분자 지원
        try:
            import re
            raw_list = re.split(r'[\n\r,;\t]+', keywords_text)
            seen = set()
            keywords = []
            for kw in raw_list:
                k = kw.strip()
                if not k or k in seen:
                    continue
                seen.add(k)
                keywords.append(k)
        except Exception:
            keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
        
        content_type = self.content_type_combo.currentText()
        if content_type == "소설":
            self.chat_log.append(f"📖 {len(keywords)}개의 키워드로 소설 작성을 시작합니다...\n")
            self.chat_log.append(f"📝 키워드: {', '.join(keywords)}\n")
            print(f"📖 {len(keywords)}개의 키워드로 소설 작성을 시작합니다...")
            print(f"📝 키워드: {', '.join(keywords)}")
        else:
            self.chat_log.append(f"🔍 {len(keywords)}개의 키워드로 멀티 검색을 시작합니다...\n")
            self.chat_log.append(f"📝 키워드: {', '.join(keywords)}\n")
            print(f"🔍 {len(keywords)}개의 키워드로 멀티 검색을 시작합니다...")
            print(f"📝 키워드: {', '.join(keywords)}")
        
        # 설정 업데이트
        self.config["tistory_enabled"] = self.tistory_checkbox.isChecked()
        self.config["naver_enabled"] = self.naver_checkbox.isChecked()
        self.config["image_source"] = self.image_source_combo.currentText()
        self.config["ad_link"] = self.ad_link_input.text().strip()
        self.config["content_type"] = self.content_type_combo.currentText()
        self.save_config()
        
        # 실행 상태 업데이트
        self.is_running = True
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.multi_search_button.setEnabled(False)
        
        # 각 키워드에 대해 GPT로 글 생성
        for i, keyword in enumerate(keywords, 1):
            if self.should_stop:
                break
                
            while self.is_paused:
                time.sleep(0.1)
                if self.should_stop:
                    break
            
            self.chat_log.append(f"📝 [{i}/{len(keywords)}] 키워드 '{keyword}' 처리 중...\n")
            print(f"📝 [{i}/{len(keywords)}] 키워드 '{keyword}' 처리 중...")
            self.send_to_gpt(keyword)
            
            # 키워드 간 간격 (설정된 분 단위, 일시정지/중지 반영)
            if i < len(keywords) and not self.should_stop:
                self.sleep_with_controls(minutes=self.config.get("post_interval_minutes", 1))
        
        # 실행 완료
        self.is_running = False
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.multi_search_button.setEnabled(True)
        
        if content_type == "소설":
            self.chat_log.append("✅ 모든 소설 작성 완료!\n")
            print("✅ 모든 소설 작성 완료!")
        else:
            self.chat_log.append("✅ 모든 키워드 처리 완료!\n")
            print("✅ 모든 키워드 처리 완료!")

    def pause_execution(self):
        """실행 일시 중지"""
        if self.is_running:
            self.is_paused = not self.is_paused
            if self.is_paused:
                self.pause_button.setText("▶️ 재개")
                self.chat_log.append("⏸️ 실행이 일시 중지되었습니다.\n")
                print("⏸️ 실행이 일시 중지되었습니다.")
            else:
                self.pause_button.setText("⏸️ 일시중지")
                self.chat_log.append("▶️ 실행이 재개되었습니다.\n")
                print("▶️ 실행이 재개되었습니다.")

    def stop_execution(self):
        """실행 강제 종료"""
        self.should_stop = True
        self.is_running = False
        self.is_paused = False
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.multi_search_button.setEnabled(True)
        self.pause_button.setText("⏸️ 일시중지")
        self.chat_log.append("🛑 실행이 강제 종료되었습니다.\n")
        print("🛑 실행이 강제 종료되었습니다.")

    def collect_google_trends_to_keywords(self):
        """구글 트렌드 수집 (수동 버튼)"""
        try:
            self.chat_log.append("📈 구글 트렌드 수집을 시작합니다...\n")
            print("📈 구글 트렌드 수집을 시작합니다...")
            
            if 'utils' in globals() and utils:
                from utils import collect_google_trends
                trends = collect_google_trends()
                if trends:
                    self.chat_log.append(f"✅ 트렌드 수집 완료: {trends[:200]}...\n")
                    print(f"✅ 트렌드 수집 완료: {trends[:200]}...")
                    # 입력란 초기화 후 새로운 트렌드로 설정
                    self.keyword_input.clear()
                    self.keyword_input.setPlainText(trends)
                    self.chat_log.append("🔄 키워드 입력란이 새로운 트렌드로 초기화되었습니다.\n")
                else:
                    self.chat_log.append("❌ 트렌드 수집 실패\n")
                    print("❌ 트렌드 수집 실패")
            else:
                self.chat_log.append("⚠️ utils 모듈이 로드되지 않았습니다\n")
                print("⚠️ utils 모듈이 로드되지 않았습니다")
                
        except Exception as e:
            self.chat_log.append(f"❌ 구글 트렌드 수집 중 오류: {str(e)}\n")
            print(f"❌ 구글 트렌드 수집 중 오류: {str(e)}")

    def on_ad_link_changed(self):
        """광고 링크 입력란 변경 시 자동 저장"""
        self.config["ad_link"] = self.ad_link_input.text().strip()
        self.save_config()
        print(f"💾 광고 링크 자동 저장: {self.config['ad_link']}")
    
    def on_content_type_changed(self):
        """콘텐츠 타입이 변경될 때 호출되는 함수"""
        content_type = self.content_type_combo.currentText()
        self.config["content_type"] = content_type
        
        # 콘텐츠 타입에 따라 UI 업데이트
        if content_type == "소설":
            # 소설 모드: 웹 검색 비활성화, 소설 프롬프트로 변경
            self.input_box.setPlaceholderText("✍️ GPT에게 소설 주제를 입력하세요...")
            self.image_prompt_input.setPlaceholderText("🎨 소설용 이미지 프롬프트 요청사항을 입력하세요 (예: 판타지 스타일, 로맨틱 분위기, 액션 장면 등)")
            
            # 소설 모드로 변경 시 이미지 프롬프트를 소설용 기본값으로 자동 변경
            try:
                from prompt_templates import get_default_novel_image_prompt_requirements
                default_prompt = get_default_novel_image_prompt_requirements()
                self.image_prompt_input.setPlainText(default_prompt)
                self.config["image_prompt_requirements"] = default_prompt
                self.chat_log.append(f"🔄 소설 모드로 변경되어 이미지 프롬프트가 소설용 기본값으로 자동 변경되었습니다.\n")
                print(f"🔄 소설 모드 이미지 프롬프트 자동 변경: {default_prompt}")
            except ImportError:
                # prompt_templates 모듈이 없을 경우 하드코딩된 기본값 사용
                default_prompt = "판타지 스타일, 로맨틱 분위기, 4K 고화질, 상세한 묘사, 감정적 표현"
                self.image_prompt_input.setPlainText(default_prompt)
                self.config["image_prompt_requirements"] = default_prompt
                self.chat_log.append(f"🔄 소설 모드로 변경되어 이미지 프롬프트가 소설용 기본값으로 자동 변경되었습니다.\n")
                print(f"🔄 소설 모드 이미지 프롬프트 자동 변경: {default_prompt}")
                
        else:
            # 블로그 모드: 웹 검색 활성화, 블로그 프롬프트로 변경
            self.input_box.setPlaceholderText("✍️ GPT에게 블로그 주제를 입력하세요...")
            self.image_prompt_input.setPlaceholderText("🎨 이미지 프롬프트 요청사항을 입력하세요 (예: 4K 고화질, 게임 스타일, 어두운 분위기, 전투 장면 등)")
            
            # 블로그 모드로 변경 시 이미지 프롬프트를 블로그용 기본값으로 자동 변경
            try:
                from prompt_templates import get_default_image_prompt_requirements
                default_prompt = get_default_image_prompt_requirements()
                self.image_prompt_input.setPlainText(default_prompt)
                self.config["image_prompt_requirements"] = default_prompt
                self.chat_log.append(f"🔄 블로그 모드로 변경되어 이미지 프롬프트가 블로그용 기본값으로 자동 변경되었습니다.\n")
                print(f"🔄 블로그 모드 이미지 프롬프트 자동 변경: {default_prompt}")
            except ImportError:
                # prompt_templates 모듈이 없을 경우 하드코딩된 기본값 사용
                default_prompt = "4K 고화질, 디테일하고 자세한 이미지, 현실적인 스타일"
                self.image_prompt_input.setPlainText(default_prompt)
                self.config["image_prompt_requirements"] = default_prompt
                self.chat_log.append(f"🔄 블로그 모드로 변경되어 이미지 프롬프트가 블로그용 기본값으로 자동 변경되었습니다.\n")
                print(f"🔄 블로그 모드 이미지 프롬프트 자동 변경: {default_prompt}")
        
        self.save_config()
        print(f"💾 콘텐츠 타입 자동 저장: {content_type}")

    def test_mysql_handler(self):
        """MySQL 핸들러 테스트"""
        try:
            self.chat_log.append("🗄️ MySQL 핸들러 테스트를 시작합니다...\n")
            print("🗄️ MySQL 핸들러 테스트를 시작합니다...")
            
            if 'mysql_handler' in globals() and mysql_handler:
                from mysql_handler import MySQLHandler
                
                # 핸들러 인스턴스 생성
                handler = MySQLHandler()
                
                # 연결 테스트
                if handler.test_connection():
                    self.chat_log.append("✅ MySQL 연결 테스트 성공\n")
                    print("✅ MySQL 연결 테스트 성공")
                else:
                    self.chat_log.append("⚠️ MySQL 연결 실패 - 로컬 파일 저장 모드\n")
                    print("⚠️ MySQL 연결 실패 - 로컬 파일 저장 모드")
                
                # 테스트 데이터 저장
                test_subject = "MySQL 핸들러 테스트 제목"
                test_content = "이것은 MySQL 핸들러 테스트를 위한 내용입니다."
                test_category = "테스트"
                test_keyword = "mysql_test"
                
                success = handler.insert_to_mysql_with_fallback(
                    test_subject, test_content, test_category, test_keyword
                )
                
                if success:
                    self.chat_log.append("✅ 테스트 데이터 저장 성공\n")
                    print("✅ 테스트 데이터 저장 성공")
                else:
                    self.chat_log.append("❌ 테스트 데이터 저장 실패\n")
                    print("❌ 테스트 데이터 저장 실패")
                    
            else:
                self.chat_log.append("⚠️ MySQL 핸들러가 로드되지 않았습니다\n")
                print("⚠️ MySQL 핸들러가 로드되지 않았습니다")
                
        except Exception as e:
            self.chat_log.append(f"❌ MySQL 핸들러 테스트 중 오류: {str(e)}\n")
            print(f"❌ MySQL 핸들러 테스트 중 오류: {str(e)}")

    def generate_gpt_image_prompt(self):
        """GPT를 사용하여 이미지 프롬프트 생성"""
        try:
            user_input = self.input_box.text().strip()
            image_requirements = self.image_prompt_input.toPlainText().strip()

            if not user_input:
                self.chat_log.append("❌ 먼저 주제를 입력해주세요.\n")
                return

            self.chat_log.append("🤖 GPT로 이미지 프롬프트를 생성합니다...\n")
            print("🤖 GPT로 이미지 프롬프트를 생성합니다...")

            # 시스템/유저 프롬프트는 신/구 SDK 모두에서 사용하므로 먼저 구성
            system_prompt = """당신은 전문적인 이미지 프롬프트 생성 전문가입니다.
            주어진 주제와 요청사항을 바탕으로 4K 고화질, 디테일하고 자세한 이미지 프롬프트를 생성해주세요.

            **중요한 가이드라인:**
            1. **4K 고화질**: ultra high quality, 4k, detailed, sharp focus
            2. **구체적 묘사**: 색상, 조명, 분위기, 구도 등을 자세히 명시

            **게임 이미지 특징:**
            - 게임 엔진 렌더링 스타일
            - 디지털 아트, 3D 모델링
            - 게임 UI 요소 포함 가능
            - 밝고 선명한 색상

            **영화 이미지 특징:**
            - 시네마틱 조명
            - 필름 그레인 효과
            - 자연스러운 색감
            - 영화적 구도

            응답은 반드시 JSON 형식으로 반환해주세요:
            {
                "image_prompt": "생성된 이미지 프롬프트",
                "style_type": "게임 또는 영화",
                "description": "프롬프트 설명"
            }"""

            user_prompt = f"""주제: {user_input}
            요청사항: {image_requirements if image_requirements else '4K 고화질, 디테일하고 자세한 이미지'}

            위 주제와 요청사항을 바탕으로 이미지 프롬프트를 생성해주세요."""

            # 신형 SDK 우선 시도
            from openai import OpenAI
            client = OpenAI(api_key=openai.api_key)

            result = self.gpt(
                user_content=user_prompt,
                system_content=system_prompt,
                temperature=0.7,
                max_tokens=500,
            )
            
            # JSON 파싱
            try:
                import json
                prompt_data = json.loads(result)
                generated_prompt = prompt_data.get("image_prompt", "")
                style_type = prompt_data.get("style_type", "")
                description = prompt_data.get("description", "")
                
                # 이미지 프롬프트 입력란에 결과 표시
                self.image_prompt_input.setPlainText(generated_prompt)
                
                self.chat_log.append(f"✅ 이미지 프롬프트 생성 완료!\n")
                self.chat_log.append(f"🎨 스타일: {style_type}\n")
                self.chat_log.append(f"📝 설명: {description}\n")
                self.chat_log.append(f"🎯 프롬프트: {generated_prompt[:100]}...\n")
                
                print(f"✅ 이미지 프롬프트 생성 완료!")
                print(f"🎨 스타일: {style_type}")
                print(f"📝 설명: {description}")
                print(f"🎯 프롬프트: {generated_prompt}")
                
            except json.JSONDecodeError:
                # JSON 파싱 실패시 전체 텍스트를 프롬프트로 사용
                self.image_prompt_input.setPlainText(result)
                self.chat_log.append(f"✅ 이미지 프롬프트 생성 완료!\n")
                self.chat_log.append(f"🎯 프롬프트: {result[:100]}...\n")
                print(f"✅ 이미지 프롬프트 생성 완료!")
                print(f"🎯 프롬프트: {result}")
            
        except ImportError:
            # 구버전 API 사용 (fallback)
            # 구버전 SDK 경로에서도 gpt-5-mini만 사용, 파라미터 최소화
            response = openai.ChatCompletion.create(
                model=self.config.get("chat_model", "gpt-5-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            result = response.choices[0].message.content.strip()
            self.image_prompt_input.setPlainText(result)
            self.chat_log.append(f"✅ 이미지 프롬프트 생성 완료!\n")
            self.chat_log.append(f"🎯 프롬프트: {result[:100]}...\n")
            print(f"✅ 이미지 프롬프트 생성 완료!")
            print(f"🎯 프롬프트: {result}")
            
        except Exception as e:
            self.chat_log.append(f"❌ 이미지 프롬프트 생성 실패: {str(e)}\n")
            print(f"❌ 이미지 프롬프트 생성 실패: {str(e)}")

    def reset_image_prompt_to_default(self):
        """이미지 프롬프트를 기본값으로 복원"""
        try:
            from prompt_templates import get_default_image_prompt_requirements, get_default_novel_image_prompt_requirements
            
            # 콘텐츠 타입 확인
            content_type = self.content_type_combo.currentText()
            
            if content_type == "소설":
                default_prompt = get_default_novel_image_prompt_requirements()
            else:
                default_prompt = get_default_image_prompt_requirements()
            
            # UI 업데이트
            self.image_prompt_input.setPlainText(default_prompt)
            
            # 설정 저장
            self.config["image_prompt_requirements"] = default_prompt
            self.save_config()
            
            self.chat_log.append(f"✅ 이미지 프롬프트가 기본값으로 복원되었습니다.\n")
            print(f"✅ 이미지 프롬프트 기본값 복원 완료: {default_prompt}")
            
        except ImportError:
            # prompt_templates 모듈이 없을 경우 하드코딩된 기본값 사용
            if content_type == "소설":
                default_prompt = "판타지 스타일, 로맨틱 분위기, 4K 고화질, 상세한 묘사, 감정적 표현"
            else:
                default_prompt = "4K 고화질, 디테일하고 자세한 이미지, 현실적인 스타일"
            
            self.image_prompt_input.setPlainText(default_prompt)
            self.config["image_prompt_requirements"] = default_prompt
            self.save_config()
            
            self.chat_log.append(f"✅ 이미지 프롬프트가 기본값으로 복원되었습니다.\n")
            print(f"✅ 이미지 프롬프트 기본값 복원 완료: {default_prompt}")
            
        except Exception as e:
            self.chat_log.append(f"❌ 이미지 프롬프트 기본값 복원 실패: {str(e)}\n")
            print(f"❌ 이미지 프롬프트 기본값 복원 실패: {str(e)}")

    def extract_json_from_text(self, text):
        """텍스트에서 JSON 블록을 추출하는 함수"""
        try:
            print(f"🔍 JSON 추출 시작 - 텍스트 길이: {len(text)}")
            
            # 1. 코드 블록에서 JSON 추출 시도 (가장 정확)
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
            
            # 2. 중괄호로 둘러싸인 JSON 객체 추출 (더 정확한 패턴)
            json_patterns = [
                r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",  # 중첩된 중괄호 처리
                r"\{[^}]*\}",  # 단순한 중괄호
                r"\{[\s\S]*?\}"  # 모든 문자 포함
            ]
            
            for pattern in json_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    try:
                        # JSON 유효성 검사
                        json.loads(match)
                        print(f"✅ 정규식 패턴에서 JSON 추출 성공: {pattern}")
                        return match
                    except:
                        continue
            
            # 3. 텍스트 정리 후 재시도 (이모지 및 특수 문자 제거)
            cleaned_text = text
            # 이모지 제거
            cleaned_text = re.sub(r'[^\x00-\x7F]+', '', cleaned_text)
            # 마크다운 제거
            cleaned_text = re.sub(r"^\s*[*\-+]\s*", "", cleaned_text, flags=re.MULTILINE)
            cleaned_text = re.sub(r"^\s*#+\s*", "", cleaned_text, flags=re.MULTILINE)
            # 불필요한 공백 제거
            cleaned_text = re.sub(r'\n\s*\n', '\n', cleaned_text)
            
            # 정리된 텍스트에서 JSON 재검색
            for pattern in json_patterns:
                matches = re.findall(pattern, cleaned_text)
                for match in matches:
                    try:
                        json.loads(match)
                        print(f"✅ 정리된 텍스트에서 JSON 추출 성공")
                        return match
                    except:
                        continue
            
            # 4. 마지막 시도: 텍스트에서 JSON 형태 찾기
            print(f"🔍 텍스트 내용 미리보기: {text[:200]}...")
            
            # 텍스트에서 JSON 키워드 찾기
            if '"final_title"' in text or '"section_titles"' in text:
                # JSON 키워드 주변 텍스트 추출
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
    
    def create_fallback_section_data(self, section_title, response_text):
        """JSON 파싱 실패 시 대체 섹션 데이터 생성"""
        try:
            # 응답 텍스트에서 내용 추출 시도
            content = response_text.strip()
            
            # 마크다운이나 특수 문자 제거
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            content = re.sub(r'^\s*[*\-+]\s*', '', content, flags=re.MULTILINE)
            content = re.sub(r'^\s*#+\s*', '', content, flags=re.MULTILINE)
            
            # JSON 형식이 아닌 일반 텍스트로 처리
            if len(content) > 50:  # 최소 길이 확인
                # 더 상세한 이미지 프롬프트 생성
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
    
    def extract_section_titles_from_text(self, text):
        """텍스트에서 섹션 제목을 추출하는 대체 방법"""
        try:
            print(f"🔍 텍스트에서 섹션 제목 추출 시도...")
            
            # 1. 번호가 있는 제목 패턴 찾기
            patterns = [
                r'(\d+\.\s*[^\n]+)',  # 1. 제목
                r'(\d+\)\s*[^\n]+)',  # 1) 제목
                r'([A-Z][^.\n]+\.)',  # 대문자로 시작하는 문장
                r'([가-힣][^.\n]+에\s+대해)',  # "~에 대해" 패턴
                r'([가-힣][^.\n]+의\s+특징)',  # "~의 특징" 패턴
                r'([가-힣][^.\n]+방법)',  # "~방법" 패턴
            ]
            
            titles = []
            for pattern in patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    title = match.strip()
                    if len(title) > 3 and len(title) < 50:  # 적절한 길이
                        titles.append(title)
            
            # 2. 중복 제거 및 정리 (공백 제거 후 비교)
            unique_titles = []
            seen_titles = set()
            for title in titles:
                # 공백 제거 후 소문자로 변환하여 비교 (대소문자 무시)
                normalized = title.strip().lower()
                if normalized and normalized not in seen_titles:
                    seen_titles.add(normalized)
                    unique_titles.append(title)
            
            # 3. 최대 5개까지만 반환
            if unique_titles:
                result = unique_titles[:5]
                print(f"✅ 섹션 제목 추출 성공: {result}")
                return result
            
            # 4. 기본 섹션 제목 생성
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
            
            # 1. JSON 블록 추출
            json_block = self.extract_json_from_text(response_text)
            if not json_block:
                print(f"❌ JSON 블록을 찾을 수 없습니다")
                print(f"📄 원본 응답 미리보기: {response_text[:300]}...")
                
                # 대체 방법: 텍스트에서 섹션 제목 추출 시도
                print(f"🔄 대체 방법으로 섹션 제목 추출 시도...")
                fallback_titles = self.extract_section_titles_from_text(response_text)
                if fallback_titles:
                    print(f"✅ 대체 방법으로 섹션 제목 추출 성공: {fallback_titles}")
                    # 키워드를 기반으로 적절한 제목 생성
                    generated_title = f"{keyword} - 상세 분석 및 가이드"
                    return fallback_titles, generated_title
                else:
                    raise ValueError("JSON 블록을 찾을 수 없습니다")
            
            # 2. JSON 파싱 시도 (여러 방법)
            parsed = None
            
            # 방법 1: json5로 시도
            try:
                parsed = json5.loads(json_block)
                print(f"✅ json5로 파싱 성공")
            except Exception as e:
                print(f"⚠️ json5 파싱 실패: {e}")
            
            # 방법 2: 표준 json으로 시도
            if not parsed:
                try:
                    parsed = json.loads(json_block)
                    print(f"✅ 표준 json으로 파싱 성공")
                except Exception as e:
                    print(f"⚠️ 표준 json 파싱 실패: {e}")
            
            # 방법 3: 문자열 정리 후 다시 시도
            if not parsed:
                try:
                    # 특수 문자 제거 및 정리
                    cleaned_json = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_block)
                    cleaned_json = re.sub(r'[^\x20-\x7e]', '', cleaned_json)
                    parsed = json.loads(cleaned_json)
                    print(f"✅ 정리된 json으로 파싱 성공")
                except Exception as e:
                    print(f"⚠️ 정리된 json 파싱 실패: {e}")
            
            # 방법 4: 이모지 및 특수 문자 제거 후 시도
            if not parsed:
                try:
                    # 이모지 및 특수 문자 제거
                    cleaned_json = re.sub(r'[^\x00-\x7F]+', '', json_block)
                    # JSON 형식 정리
                    cleaned_json = re.sub(r'[^\x20-\x7e]', '', cleaned_json)
                    parsed = json.loads(cleaned_json)
                    print(f"✅ 이모지 제거 후 json 파싱 성공")
                except Exception as e:
                    print(f"⚠️ 이모지 제거 후 json 파싱 실패: {e}")
            
            if not parsed:
                print(f"❌ 모든 JSON 파싱 방법 실패")
                print(f"📄 JSON 블록: {json_block}")
                raise ValueError("JSON 파싱에 실패했습니다")
            
            # 3. 데이터 검증 및 정리
            section_titles_raw = parsed.get("section_titles", [])
            final_title = parsed.get("final_title", "❌ 없음")
            
            # section_titles가 문자열 리스트인지 확인하고 정리
            section_titles_temp = []
            for title in section_titles_raw:
                if isinstance(title, str):
                    section_titles_temp.append(title)
                else:
                    print(f"⚠️ 잘못된 섹션 제목 타입: {type(title)}, 값: {title}")
                    # 불린 값이나 다른 타입을 문자열로 변환
                    section_titles_temp.append(str(title))
            
            # 중복 제목 제거 (공백 제거 후 비교)
            section_titles = []
            seen_titles = set()
            for title in section_titles_temp:
                # 공백 제거 후 소문자로 변환하여 비교 (대소문자 무시)
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
                    # final_title이 기본값이면 키워드 기반으로 생성
                    if final_title == "❌ 없음" or final_title == "자동 생성된 제목":
                        final_title = f"{keyword} - 종합 분석 리포트"
                    return fallback_titles, final_title
                else:
                    raise ValueError("섹션 제목이 없습니다")
            
            # 중복 제거 후 개수가 부족한 경우 기본 제목으로 보완
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

    def generate_section_content(self, section_title, final_title, keyword, clean_trimmed_text, i, previous_sections_content=""):
        """개별 섹션의 내용을 생성하는 함수 (웹 수집 + GPT 생성)"""
        self.chat_log.append(f"📝 [{i+1}] 섹션 '{section_title}' 웹 수집 및 내용 생성 중...\n")
        print(f"📝 [{i+1}] 섹션 '{section_title}' 웹 수집 및 내용 생성 중...")
        
        try:
            # 1단계: 웹 수집을 통한 실제 데이터 수집
            collected_data = self.collect_web_data_for_section(section_title, keyword, clean_trimmed_text)
            
            # 2단계: 수집된 데이터를 바탕으로 섹션별 프롬프트 생성
            section_prompt = self.build_section_prompt_with_web_data(
                section_title, final_title, keyword, clean_trimmed_text, 
                collected_data, previous_sections_content
            )
            
            # 3단계: GPT로 섹션 내용 생성
            response_text = self.gpt(
                user_content=section_prompt,
                temperature=0.3,
                max_tokens=700,
            )
            json_block = self.extract_json_from_text(response_text)
            
            if not json_block:
                print(f"❌ JSON 블록을 찾을 수 없습니다 - 재시도 시도")
                # JSON 강제 재시도 (최소 300자 이상)
                retry_prompt = section_prompt + f"\n\n중요: 반드시 아래 JSON 형식으로만 응답하고, 본문(content)은 최소 300자 이상으로 작성하세요. 설명 금지.\n```json\n{{\n  \"section_title\": \"{section_title}\",\n  \"content\": \"HTML 형식의 섹션 내용 (제목 제외)\",\n  \"image_prompt\": \"이 섹션을 위한 상세한 이미지 프롬프트 (한국어, 100자 이상 권장)\"\n}}\n```"
                retry_text = self.gpt(
                    user_content=retry_prompt,
                    temperature=0.3,
                    max_tokens=900,
                )
                json_block = self.extract_json_from_text(retry_text)
                if not json_block:
                    print(f"❌ 재시도 후에도 JSON 블록 없음 - 대체 방법 시도")
                    # 대체 방법으로 섹션 데이터 생성
                    fallback_data = self.create_fallback_section_data(section_title, retry_text or response_text)
                    if fallback_data:
                        print(f"✅ 대체 방법으로 섹션 데이터 생성 성공")
                        return fallback_data
                    else:
                        raise ValueError("JSON 형식이 감지되지 않음")

            if json_block and json_block.strip():
                # JSON 파싱 시도 (여러 방법)
                section_data = None
                
                # 방법 1: json5로 시도
                try:
                    section_data = json5.loads(json_block)
                except Exception as e:
                    print(f"⚠️ json5 파싱 실패: {e}")
                
                # 방법 2: 표준 json으로 시도
                if not section_data:
                    try:
                        section_data = json.loads(json_block)
                    except Exception as e:
                        print(f"⚠️ json 파싱 실패: {e}")
                
                # 방법 3: 문자열 정리 후 다시 시도
                if not section_data:
                    try:
                        # 특수 문자 제거 및 정리
                        cleaned_json = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_block)
                        cleaned_json = re.sub(r'[^\x20-\x7e]', '', cleaned_json)
                        section_data = json.loads(cleaned_json)
                    except Exception as e:
                        print(f"⚠️ 정리된 json 파싱 실패: {e}")
                
                if not section_data:
                    print(f"❌ 모든 JSON 파싱 방법 실패")
                    print(f"📄 JSON 블록: {json_block}")
                    print(f"📄 원본 응답 길이: {len(response_text)}")
                    print(f"📄 JSON 블록 길이: {len(json_block)}")
                    print(f"🔄 대체 방법으로 처리 시도...")
                    
                    # 대체 방법으로 섹션 데이터 생성
                    fallback_data = self.create_fallback_section_data(section_title, response_text)
                    if fallback_data:
                        print(f"✅ 대체 방법으로 섹션 데이터 생성 성공")
                        return fallback_data
                    else:
                        raise ValueError("JSON 파싱에 실패했습니다")
                
                print(f"✅ 섹션 JSON 파싱 성공!")
                
                # section_data가 올바른 형식인지 확인
                if not isinstance(section_data, dict):
                    raise ValueError("섹션 데이터가 딕셔너리가 아닙니다")
                
                # 필수 필드 확인
                if "section_title" not in section_data or "content" not in section_data:
                    raise ValueError("섹션 데이터에 필수 필드가 없습니다")
                
                # 문자열 타입 확인 및 변환
                section_title = str(section_data.get("section_title", ""))
                content = str(section_data.get("content", ""))
                
                if not section_title or not content:
                    raise ValueError("섹션 제목이나 내용이 비어있습니다")

                # 본문 길이 검증 (HTML 태그 제거 후 300자 미만이면 1회 재시도)
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
                            section_title = str(section_data_retry.get("section_title", section_title))
                            content = str(section_data_retry.get("content", content))
                            image_prompt = section_data_retry.get("image_prompt", section_data.get("image_prompt", ""))
                        except Exception:
                            pass
                
                # 이미지 프롬프트 추출 (길이 제한 없이)
                image_prompt = section_data.get("image_prompt", "")
                if image_prompt:
                    print(f"🎨 섹션에서 추출된 이미지 프롬프트: {image_prompt}")
                else:
                    print(f"⚠️ 섹션에서 이미지 프롬프트가 없습니다")
                
                # 정리된 데이터로 교체 (이미지 프롬프트 길이 보존)
                section_data = {
                    "section_title": section_title,
                    "content": content,
                    "image_prompt": image_prompt
                }
                
                print(f"✅ 섹션 데이터 생성 완료:")
                print(f"   - 제목: {section_title}")
                print(f"   - 내용 길이: {len(content)}자")
                print(f"   - 이미지 프롬프트 길이: {len(image_prompt)}자")
                
                return section_data
            else:
                raise ValueError("JSON 블록이 비어있습니다")
            
        except Exception as e:
            raise Exception(f"섹션 내용 생성 실패: {e}")

    def collect_web_data_for_section(self, section_title, keyword, clean_trimmed_text):
        """섹션별 데이터 제공 (이미 정리된 데이터 사용)"""
        try:
            self.chat_log.append(f"📝 섹션 데이터 준비 중: {section_title}\n")
            print(f"📝 섹션 데이터 준비 중: {section_title}")
            
            # 이미 정리된 데이터 사용 (별도 수집 없음)
            organized_data = getattr(self, 'collected_web_data', '')
            
            if organized_data:
                # 정리된 데이터를 섹션별로 활용
                result = {
                    "search_keywords": keyword,  # 사용자 검색어 그대로 사용
                    "web_contents": [organized_data[:1500]],  # 정리된 데이터 사용
                    "urls": getattr(self, 'collected_urls', [f"https://www.bing.com/search?q={keyword}"]),
                    "titles": [f"{section_title} 관련 정보"]
                }
                
                print(f"✅ 섹션 데이터 준비 완료: {len(organized_data)}자")
                return result
            else:
                # 정리된 데이터가 없으면 기본 데이터
                return {
                    "search_keywords": keyword,
                    "web_contents": [f"{section_title}에 대한 정보를 찾아보세요."],
                    "urls": getattr(self, 'collected_urls', [f"https://www.bing.com/search?q={keyword}"]),
                    "titles": [f"{section_title} 검색 결과"]
                }
            
        except Exception as e:
            print(f"❌ 섹션 데이터 준비 실패: {e}")
            # 오류 시 기본 데이터 반환
            return {
                "search_keywords": keyword,
                "web_contents": [f"{section_title}에 대한 정보를 찾아보세요."],
                "urls": getattr(self, 'collected_urls', [f"https://www.bing.com/search?q={keyword}"]),
                "titles": [f"{section_title} 검색 결과"]
            }

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
                primary_model=self.config.get("chat_model", "gpt-5-mini"),
                temperature=0.3,
                max_tokens=50
            )
            
            generated_keywords = response.choices[0].message.content.strip()
            
            # 검색어 정리 (특수문자 제거, 길이 제한)
            generated_keywords = re.sub(r'[^\w\s가-힣]', ' ', generated_keywords)
            generated_keywords = ' '.join(generated_keywords.split())
            
            # 길이 제한 (너무 길면 앞부분만 사용)
            if len(generated_keywords) > 50:
                generated_keywords = ' '.join(generated_keywords.split()[:3])
            
            # 빈 검색어 검증
            if not generated_keywords or len(generated_keywords.strip()) < 2:
                print(f"⚠️ GPT 메인 검색어 생성 실패, 기본 검색어 사용")
                generated_keywords = keyword.strip()
                generated_keywords = re.sub(r'[^\w\s가-힣]', ' ', generated_keywords)
                generated_keywords = ' '.join(generated_keywords.split()[:3])
            
            print(f"✅ GPT 메인 검색어 생성 완료: '{generated_keywords}' (길이: {len(generated_keywords)}자)")
            return generated_keywords
            
        except Exception as e:
            print(f"❌ GPT 메인 검색어 생성 실패: {e}")
            # 실패 시 기본 검색어 사용
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
                primary_model=self.config.get("chat_model", "gpt-5-mini"),
                temperature=0.3,
                max_tokens=2000
            )
            
            organized_data = response.choices[0].message.content.strip()
            
            print(f"✅ 데이터 정리 완료: {len(organized_data)}자")
            return organized_data
            
        except Exception as e:
            print(f"❌ 데이터 정리 실패: {e}")
            # 실패 시 원본 데이터 반환
            return collected_data[:2000] if len(collected_data) > 2000 else collected_data

    def generate_optimal_search_keywords(self, section_title, keyword, clean_trimmed_text):
        """섹션별 검색어 생성 함수 (원래 방식)"""
        try:
            # 간단하게 섹션 제목과 키워드를 조합
            search_keywords = f"{section_title} {keyword}".strip()
            search_keywords = re.sub(r'[^\w\s가-힣]', ' ', search_keywords)
            search_keywords = ' '.join(search_keywords.split()[:3])  # 최대 3개 단어로 제한
            
            # 최종 길이 제한 (50자 이하)
            if len(search_keywords) > 50:
                search_keywords = search_keywords[:50].rsplit(' ', 1)[0]  # 마지막 단어가 잘리지 않도록
            
            print(f"✅ 섹션 검색어 생성 완료: '{search_keywords}' (길이: {len(search_keywords)}자)")
            return search_keywords
            
        except Exception as e:
            print(f"❌ 섹션 검색어 생성 실패: {e}")
            # 실패 시 기본 검색어 사용
            fallback_keywords = f"{section_title} {keyword}".strip()
            fallback_keywords = re.sub(r'[^\w\s가-힣]', ' ', fallback_keywords)
            fallback_keywords = ' '.join(fallback_keywords.split()[:3])
            return fallback_keywords

    def generate_image_prompt_from_content(self, section_data):
        """섹션 내용을 토대로 이미지 프롬프트를 생성하는 함수"""
        try:
            section_title = section_data["section_title"]
            content = section_data["content"]
            
            # HTML 태그 제거하여 순수 텍스트 추출
            import re
            clean_content = re.sub(r'<[^>]+>', '', content)
            
            # 사용자가 입력한 이미지 프롬프트 요청사항 가져오기
            image_requirements = self.config.get("image_prompt_requirements", "")
            
            # 콘텐츠 타입 확인
            content_type = self.content_type_combo.currentText()
            
            if content_type == "소설":
                # 소설용 이미지 프롬프트
                prompt = f"""
다음 소설 장면을 바탕으로 이미지 프롬프트를 생성해주세요.

📖 장면 제목: {section_title}
📄 장면 내용: {clean_content[:800]}  # 더 많은 내용 제공

🎨 사용자 요청사항: {image_requirements}

**소설용 이미지 프롬프트 가이드라인:**
- 등장인물의 감정과 표정을 강조
- 장면의 분위기와 감정을 시각적으로 표현
- 배경과 설정을 생생하게 묘사
- 소설의 장르에 맞는 스타일 적용 (판타지, 로맨스, 액션 등)
- 4K 고화질, 상세한 묘사
- 감정적이고 몰입감 있는 이미지

**출력 형식:**
다음 형식으로 정확히 출력해주세요:

**이미지 스타일:**
[스타일 관련 내용만 작성]

**장면 내용:**
[장면 내용만 작성]

예시:
**이미지 스타일:**
일본 애니메이션 스타일, 4K 고화질, 상세한 묘사, 감정적 표현, 판타지 분위기

**장면 내용:**
강호인이 복도를 걷다가 멈춰선 순간. 그의 표정은 혼란과 경계심이 뒤섞인 복잡한 감정을 드러내고 있으며, 주변은 생동감 있게 그려져 있다. 식당의 소음, 자판기의 딸깍거림, 선반 위의 잡지들이 어제와 똑같은 모습으로 배경에 놓여 있다. 강호인의 눈빛은 과거의 기억과 현재의 반복 사이에서 갈등하는 듯하며, 그의 주변에는 흐릿한 형체의 백운노가 허공을 가르며 나타나고 있다. 백운노는 강호인의 얼굴로 변형되어 있으며, 그의 입에서 "나는 네 기억 속 백운노다."라는 말이 흘러나오는 순간을 강조한다. PX 뒤편의 부적이 떨리며 기운이 침투하는 장면은 긴장감을 더하고, 전체적으로 판타지와 스릴이 어우러진 분위기를 만들어낸다.
"""
            else:
                # 블로그용 이미지 프롬프트 (개선)
                prompt = f"""
다음 섹션 내용을 바탕으로 이미지 프롬프트를 생성해주세요.

📝 섹션 제목: {section_title}
📄 섹션 내용: {clean_content[:800]}  # 더 많은 내용 제공

🎨 사용자 요청사항: {image_requirements}

**블로그용 이미지 프롬프트 가이드라인:**
- 섹션 내용의 핵심을 시각적으로 표현
- 전문적이고 깔끔한 스타일
- 현대적이고 매력적인 디자인
- 색상과 분위기를 명확히 지정
- 4K 고화질, 상세한 묘사

**출력 형식:**
다음 형식으로 정확히 출력해주세요:

**이미지 스타일:**
[스타일 관련 내용만 작성]

**장면 내용:**
[장면 내용만 작성]

예시:
**이미지 스타일:**
현대적 디자인, 4K 고화질, 전문적 스타일, 깔끔한 레이아웃, 매력적인 색상

**장면 내용:**
[섹션 내용에 맞는 구체적인 장면 설명]
"""
            
            image_prompt_raw_string = self.gpt(
                user_content=prompt,
                system_content="텍스트 내용을 바탕으로 이미지 프롬프트를 생성하는 전문가입니다.",
                temperature=1,
                max_tokens=500,
            )
            print(f"✅ 이미지 프롬프트 생성 완료: '{image_prompt_raw_string}'")
            
            # 이미지 프롬프트를 스타일과 내용으로 분리
            parsed_prompt_dict = self.parse_image_prompt(image_prompt_raw_string)
            return (parsed_prompt_dict, image_prompt_raw_string)
            
        except Exception as e:
            print(f"❌ 이미지 프롬프트 생성 실패: {e}")
            # 실패 시 섹션 제목을 기반으로 기본 프롬프트 생성
            fallback_prompt = f"{section_data['section_title']} illustration, 4K 고화질, 상세한 묘사"
            fallback_dict = {
                "style": "4K 고화질, 상세한 묘사",
                "content": f"{section_data['section_title']} illustration"
            }
            return (fallback_dict, fallback_prompt)

    def parse_image_prompt(self, image_prompt):
        """이미지 프롬프트를 스타일과 내용으로 분리하는 함수"""
        try:
            # **이미지 스타일:** 와 **장면 내용:** 패턴으로 분리
            import re
            
            style_match = re.search(r'\*\*이미지 스타일:\*\*\s*(.*?)(?=\*\*장면 내용:\*\*|\Z)', image_prompt, re.DOTALL)
            content_match = re.search(r'\*\*장면 내용:\*\*\s*(.*?)(?=\*\*|\Z)', image_prompt, re.DOTALL)
            
            if style_match and content_match:
                style = style_match.group(1).strip()
                content = content_match.group(1).strip()
                
                print(f"✅ 이미지 프롬프트 파싱 완료:")
                print(f"   스타일: {style}")
                print(f"   내용: {content}")
                
                return {
                    "style": style,
                    "content": content
                }
            else:
                # 파싱 실패 시 원본 텍스트를 분석하여 스타일과 내용 분리
                print(f"⚠️ 정규식 파싱 실패, 텍스트 분석으로 분리 시도")
                
                # 원본 텍스트에서 스타일 관련 키워드 찾기
                style_keywords = ["4K", "고화질", "상세한", "묘사", "감정적", "표현", "판타지", "스릴러", "분위기", "애니메이션", "스타일"]
                content_keywords = ["강호인", "복도", "표정", "혼란", "경계심", "감정", "주변", "생동감", "식당", "소음", "자판기", "선반", "잡지", "배경", "눈빛", "기억", "현재", "반복", "갈등", "흐릿한", "형체", "백운노", "허공", "얼굴", "변형", "입", "말", "부적", "떨림", "기운", "침투", "긴장감"]
                
                text = image_prompt.strip()
                
                # 스타일과 내용을 분리하는 로직
                if "," in text:
                    parts = text.split(",")
                    
                    # 스타일 부분 찾기 (마지막 부분에 스타일 키워드가 있는 경우)
                    style_parts = []
                    content_parts = []
                    
                    for part in parts:
                        part = part.strip()
                        is_style = any(keyword in part for keyword in style_keywords)
                        
                        if is_style:
                            style_parts.append(part)
                        else:
                            content_parts.append(part)
                    
                    # 스타일이 없으면 마지막 3-4개 부분을 스타일로 간주
                    if not style_parts and len(parts) >= 4:
                        style_parts = parts[-4:]
                        content_parts = parts[:-4]
                    
                    style = ", ".join(style_parts) if style_parts else "4K 고화질, 상세한 묘사"
                    content = ", ".join(content_parts) if content_parts else text
                    
                    print(f"✅ 텍스트 분석으로 파싱 완료:")
                    print(f"   스타일: {style}")
                    print(f"   내용: {content}")
                    
                    return {
                        "style": style,
                        "content": content
                    }
                else:
                    # 쉼표가 없으면 전체를 내용으로, 기본 스타일 적용
                    return {
                        "style": "4K 고화질, 상세한 묘사",
                        "content": text
                    }
                
        except Exception as e:
            print(f"❌ 이미지 프롬프트 파싱 오류: {e}")
            return {
                "style": "4K 고화질, 상세한 묘사",
                "content": image_prompt.strip()
            }

    def generate_section_image_with_prompt(self, section_data, image_prompt, i, section_titles):
        """이미지 프롬프트를 사용하여 섹션별 이미지를 생성하는 함수"""
        image_url = None
        
        # 랜덤 확률 적용
        use_random_probability = self.config.get("use_random_probability", False)
        random_probability = self.config.get("random_probability", 85)
        
        if use_random_probability:
            import random
            if random.randint(1, 100) > random_probability:
                print(f"🎲 랜덤 확률({random_probability}%)에 의해 섹션 {i+1} 이미지 생성 건너뜀")
                self.chat_log.append(f"🎲 랜덤 확률({random_probability}%)에 의해 섹션 {i+1} 이미지 생성 건너뜀\n")
                return None
        
        image_source = self.config.get("image_source", "bing")
        bing_image_count = self.config.get("bing_image_count", 3)
        
        print(f"🔍 섹션 {i+1} 이미지 소스: {image_source}")
        
        # 이미지 프롬프트가 튜플 형태인지 확인 (파싱된 딕셔너리와 원본 문자열)
        if isinstance(image_prompt, tuple) and len(image_prompt) == 2:
            parsed_prompt_dict, image_prompt_raw_string = image_prompt
            
            style = parsed_prompt_dict.get("style", "")
            content = parsed_prompt_dict.get("content", "")
            
            # The full prompt for the image generation model should be the raw string from GPT
            full_prompt = image_prompt_raw_string 
            
            print(f"🎨 이미지 스타일 (파싱): {style}")
            print(f"🎨 장면 내용 (파싱): {content}")
            print(f"🎨 전체 프롬프트 (원본 GPT 응답): {full_prompt}")
            
            # 섹션 데이터에 분리된 정보도 저장
            section_data["image_prompt"] = full_prompt # This is the prompt sent to image generation
            section_data["image_style"] = style
            section_data["image_content"] = content
        elif isinstance(image_prompt, dict):
            # 기존 딕셔너리 형태의 프롬프트 (하위 호환성)
            style = image_prompt.get("style", "")
            content = image_prompt.get("content", "")
            full_prompt = f"{style}, {content}"
            print(f"🎨 이미지 스타일: {style}")
            print(f"🎨 장면 내용: {content}")
            print(f"🎨 전체 프롬프트: {full_prompt}")
            
            section_data["image_prompt"] = full_prompt
            section_data["image_style"] = style
            section_data["image_content"] = content
        else:
            # 기존 문자열 형태의 프롬프트
            full_prompt = image_prompt
            print(f"🎨 이미지 프롬프트: {image_prompt}")
            
            # 섹션 데이터에 저장
            section_data["image_prompt"] = full_prompt
        
        # 이미지 생성 시도
        if image_source == "bing":
            # full_screenshot_gpu 모듈이 있으면 사용, 없으면 다른 방법 시도
            if 'full_screenshot_gpu' in globals() and full_screenshot_gpu:
                image_url = self.generate_bing_image(section_data, i, bing_image_count)
            else:
                # 대체 방법으로 간단한 이미지 검색 시도
                image_url = self.generate_simple_image(section_data, i)
        elif image_source == "bing_sora":
            image_url = self.generate_bing_sora_image(section_data, i, bing_image_count)
        elif image_source == "sora":
            # Sora만 사용하는 옵션 (향후 구현)
            self.chat_log.append(f"⚠️ Sora 전용 옵션은 아직 구현되지 않았습니다. Bing으로 대체합니다.\n")
            if 'full_screenshot_gpu' in globals() and full_screenshot_gpu:
                image_url = self.generate_bing_image(section_data, i, bing_image_count)
            else:
                image_url = self.generate_simple_image(section_data, i)
        
        return image_url

    def generate_section_image(self, section_data, i, section_titles):
        """섹션별 이미지를 생성하는 함수 (기존 호환성용)"""
        image_url = None
        
        # 랜덤 확률 적용
        use_random_probability = self.config.get("use_random_probability", False)
        random_probability = self.config.get("random_probability", 85)
        
        if use_random_probability:
            import random
            if random.randint(1, 100) > random_probability:
                print(f"🎲 랜덤 확률({random_probability}%)에 의해 섹션 {i+1} 이미지 생성 건너뜀")
                self.chat_log.append(f"🎲 랜덤 확률({random_probability}%)에 의해 섹션 {i+1} 이미지 생성 건너뜀\n")
                return None
        
        image_source = self.config.get("image_source", "bing")
        bing_image_count = self.config.get("bing_image_count", 3)
        
        print(f"🔍 섹션 {i+1} 이미지 소스: {image_source}")
        
        # 이미지 생성 시도
        if image_source == "bing":
            # full_screenshot_gpu 모듈이 있으면 사용, 없으면 다른 방법 시도
            if 'full_screenshot_gpu' in globals() and full_screenshot_gpu:
                image_url = self.generate_bing_image(section_data, i, bing_image_count)
            else:
                # 대체 방법으로 간단한 이미지 검색 시도
                image_url = self.generate_simple_image(section_data, i)
        elif image_source == "bing_sora":
            image_url = self.generate_bing_sora_image(section_data, i, bing_image_count)
        elif image_source == "sora":
            # Sora만 사용하는 옵션 (향후 구현)
            self.chat_log.append(f"⚠️ Sora 전용 옵션은 아직 구현되지 않았습니다. Bing으로 대체합니다.\n")
            if 'full_screenshot_gpu' in globals() and full_screenshot_gpu:
                image_url = self.generate_bing_image(section_data, i, bing_image_count)
            else:
                image_url = self.generate_simple_image(section_data, i)
        
        return image_url

    def generate_simple_image(self, section_data, i):
        """간단한 이미지 생성 함수 (full_screenshot_gpu 모듈이 없을 때 사용)"""
        try:
            self.chat_log.append(f"🖼️ [{i+1}] 간단한 이미지 생성 시도...\n")
            print(f"🖼️ [{i+1}] 간단한 이미지 생성 시도...")
            
            # image_search 모듈이 있으면 사용
            if 'image_search' in globals() and image_search:
                from image_search import naver_image_search_with_rotation, upload_image_to_github
                
                # 네이버 이미지 검색
                search_query = section_data["section_title"]
                image_path = naver_image_search_with_rotation(search_query)
                
                if image_path and os.path.exists(image_path):
                    # GitHub 업로드
                    origin_url, _ = upload_image_to_github(image_path)
                    print(f"✅ 섹션 {i+1} 간단한 이미지 생성 완료: {origin_url}")
                    self.chat_log.append(f"✅ 섹션 {i+1} 간단한 이미지 생성 완료\n")
                    return origin_url
                else:
                    print(f"❌ 섹션 {i+1} 간단한 이미지 생성 실패")
            else:
                print(f"⚠️ image_search 모듈이 로드되지 않아 간단한 이미지 생성 불가")
                
        except Exception as e:
            print(f"❌ 섹션 {i+1} 간단한 이미지 생성 중 오류: {e}")
            self.chat_log.append(f"❌ 섹션 {i+1} 간단한 이미지 생성 중 오류: {e}\n")
        
        return None

    def generate_optimal_image_search_query(self, section_data: dict) -> str:
        """Bing 이미지 검색을 위한 최적 검색어를 생성 (장면과의 정합성 향상)"""
        try:
            import re

            section_title = section_data.get("section_title", "").strip()
            image_prompt = section_data.get("image_prompt", "").strip()
            image_content = section_data.get("image_content", "").strip()
            # 본문 텍스트 정제
            plain_content = re.sub(r"<[^>]+>", " ", section_data.get("content", "")).strip()

            # 검색 핵심 텍스트: 장면 내용(image_content) 우선 → 프롬프트 → 제목+본문
            core_text = (image_content or image_prompt or (section_title + " " + plain_content)).strip()

            # 1) GPT 기반: 핵심 명사만 뽑아 간결 쿼리 생성 (결정론적으로)
            prompt = (
                "아래 텍스트에서 장면과 정확히 매치되는 핵심 명사(인물/사물/장소/행동의 대상)만 골라 한국어 검색어를 생성하세요.\n"
                "- 3~8단어 이내, 공백으로만 구분\n"
                "- 형용사/스타일(예: 4K, 고화질, 현대적 등) 제외\n"
                "- 문장/설명 금지, 검색어만 출력\n"
                f"텍스트: {core_text[:500]}\n"
            )

            response = self.call_chat_with_fallback(
                messages=[
                    {"role": "system", "content": "당신은 이미지 검색 키워드에서 핵심 명사만 추출하는 전문가입니다."},
                    {"role": "user", "content": prompt},
                ],
                primary_model=self.config.get("chat_model", "gpt-5-mini"),
                temperature=0.0,
                max_tokens=50,
            )

            query = response.choices[0].message.content.strip()
            # 안전 정제
            query = re.sub(r"[\n\r]+", " ", query)
            query = re.sub(r"[\"'`<>\\|,.]+", " ", query)
            query = re.sub(r"\s+", " ", query).strip()

            # 2) 폴백: 단순 토크나이즈로 핵심 단어 추출
            if len(query) < 2:
                text = core_text
                # 기본 불용어 및 스타일 단어 제거
                stopwords = set([
                    "4K", "고화질", "상세한", "현대적", "전문적", "이미지", "스타일", "장면", "내용",
                    "그리고", "그러나", "또는", "합니다", "한다", "있는", "없는", "대한"
                ])
                # 한글/영문/숫자만 남기고 분할
                tokens = re.findall(r"[\w가-힣]+", text)
                # 길이 2 이상, 불용어 제외, 중복 제거 순서 보존
                seen = set()
                keywords = []
                for tok in tokens:
                    if len(tok) < 2:
                        continue
                    if tok in stopwords:
                        continue
                    if tok in seen:
                        continue
                    seen.add(tok)
                    keywords.append(tok)
                    if len(keywords) >= 8:
                        break
                query = " ".join(keywords) if keywords else (section_title or "이미지")

            print(f"🔍 이미지 검색어: {query}")
            return query
        except Exception as e:
            print(f"⚠️ 이미지 검색어 생성 실패: {e}")
            return section_data.get("section_title", "이미지")

    def generate_bing_image(self, section_data, i, bing_image_count):
        """Bing 이미지를 생성하는 함수"""
        self.chat_log.append(f"🖼️ [{i+1}] 섹션 이미지 생성 중...\n")
        print(f"🖼️ [{i+1}] 섹션 이미지 생성 중...")
        
        try:
            from full_screenshot.full_screenshot_gpu import download_top_bing_images_grid_match, load_blip_model
            import os
            import torch
            
            # BLIP 모델 로딩
            if not hasattr(self, "_blip_cached"):
                print("📦 BLIP 모델 로딩 중 (초기 1회)...")
                processor, model = load_blip_model()
                # GPU 우선 설정
                use_gpu = self.config.get("use_gpu_for_images", True) and torch.cuda.is_available()
                if use_gpu:
                    try:
                        model = model.to("cuda")
                        os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
                        print("✅ BLIP 모델을 CUDA로 이동 완료")
                    except Exception as move_e:
                        print(f"⚠️ BLIP CUDA 이동 실패, CPU 사용: {move_e}")
                # 캐시 보관
                self._blip_cached = (processor, model)
            else:
                processor, model = self._blip_cached
                print("♻️ BLIP 모델 캐시 재사용")
            
            # Bing 검색어: GPT-4o-mini로 생성한 최적 검색어 사용
            search_query = self.generate_optimal_image_search_query(section_data)
            
            print(f"🔍 Bing 검색어: {search_query}")
            
            # Bing 이미지 검색 및 그리드 생성
            result = download_top_bing_images_grid_match(
                search_query=search_query,  # 전체 이미지 프롬프트를 검색어로 사용
                max_images=bing_image_count,  # 설정된 Bing 이미지 개수 사용
                target_width=1024,
                output_filename=f"bing_grid_section_{i+1}.png",
                processor=processor,
                model=model,
                used_image_urls=getattr(self, 'used_image_urls', set())
            )
            
            if result and "grid_path" in result:
                local_path = f"bing_grid_section_{i+1}.png"
                if os.path.exists(local_path):
                    print(f"✅ 섹션 {i+1} 이미지 그리드 생성 완료: {local_path}")
                    
                    # GitHub 업로드
                    if 'image_search' in globals() and image_search:
                        from image_search import upload_image_to_github
                        origin_url, _ = upload_image_to_github(local_path)
                        image_url = origin_url
                        print(f"✅ 섹션 {i+1} 이미지 GitHub 업로드 완료: {origin_url}")
                        self.chat_log.append(f"✅ 섹션 {i+1} 이미지 업로드 완료\n")
                        return image_url
                    else:
                        print("⚠️ image_search 모듈이 로드되지 않아 업로드할 수 없습니다")
                else:
                    print(f"❌ 섹션 {i+1} 이미지 파일이 생성되지 않았습니다")
            else:
                print(f"❌ 섹션 {i+1} 이미지 검색 결과가 없습니다")
                
        except Exception as e:
            print(f"❌ 섹션 {i+1} 이미지 생성 중 오류: {e}")
            self.chat_log.append(f"❌ 섹션 {i+1} 이미지 생성 중 오류: {e}\n")
        
        return None

    def generate_bing_sora_image(self, section_data, i, bing_image_count):
        """Bing+Sora 이미지를 생성하는 함수"""
        self.chat_log.append(f"🎬 [{i+1}] 섹션 Bing+Sora 이미지 생성 중...\n")
        print(f"🎬 [{i+1}] 섹션 Bing+Sora 이미지 생성 중...")
        
        try:
            # sora_bing_handler 모듈 사용
            from sora_bing_handler import generate_bing_sora_images
            
            # Bing + Sora 이미지 생성 (이미지 프롬프트 전달)
            image_prompt = section_data.get("image_prompt", "")
            print(f"🔍 섹션 {i+1} 이미지 프롬프트 정보:")
            print(f"   📝 이미지 프롬프트: {image_prompt}")
            print(f"   📝 섹션 제목: {section_data['section_title']}")
            print(f"   📝 섹션 내용 길이: {len(section_data['content'])}자")
            
            # GIF 유사도 및 포함률 설정 가져오기
            similarity_threshold = self.config.get("gif_similarity", 50)
            inclusion_rate = self.config.get("gif_inclusion", 50)
            word_inclusion_threshold = self.config.get("word_inclusion_threshold", 30)
            
            result = generate_bing_sora_images(
                section_title=section_data["section_title"],
                section_content=section_data["content"],
                section_index=i+1,
                bing_image_count=bing_image_count,
                image_prompt=image_prompt,
                similarity_threshold=similarity_threshold,
                inclusion_rate=inclusion_rate,
                word_inclusion_threshold=word_inclusion_threshold
            )
            
            if result['success']:
                image_url = result['final_url']
                # 기본 플레이스홀더 GIF는 사용하지 않도록 차단
                if isinstance(image_url, str) and "images/default/default_image.gif" in image_url:
                    print("⚠️ 기본 플레이스홀더 GIF 감지 - 이미지 사용 안 함")
                    self.chat_log.append("⚠️ 기본 플레이스홀더 GIF 감지 - 이미지 제외\n")
                    return None
                
                # 상세 로그 출력
                if result['bing_url']:
                    self.chat_log.append(f"✅ 섹션 {i+1} Bing 이미지 생성 완료\n")
                    print(f"✅ 섹션 {i+1} Bing 이미지 생성 완료: {result['bing_url']}")
                
                if result['sora_url']:
                    self.chat_log.append(f"✅ 섹션 {i+1} Sora 이미지 생성 완료\n")
                    print(f"✅ 섹션 {i+1} Sora 이미지 생성 완료: {result['sora_url']}")
                
                # 최종 URL 로그 (Sora 우선)
                if result['sora_url']:
                    print(f"✅ 섹션 {i+1} Sora GIF 이미지 생성 완료 (우선 사용)")
                    self.chat_log.append(f"✅ 섹션 {i+1} Sora GIF 이미지 생성 완료 (우선 사용)\n")
                elif result['bing_url']:
                    print(f"✅ 섹션 {i+1} Bing 이미지 생성 완료 (Sora 실패시 대체)")
                    self.chat_log.append(f"✅ 섹션 {i+1} Bing 이미지 생성 완료 (Sora 실패시 대체)\n")
                else:
                    print(f"✅ 섹션 {i+1} 기본 GIF 이미지 생성 완료 (무조건 성공)")
                    self.chat_log.append(f"✅ 섹션 {i+1} 기본 GIF 이미지 생성 완료 (무조건 성공)\n")
                
                print(f"✅ 섹션 {i+1} 최종 이미지 URL: {image_url}")
                return image_url
            else:
                print(f"⚠️ 섹션 {i+1} Bing+Sora 이미지 생성 실패 - 이미지 없음")
                self.chat_log.append(f"⚠️ 섹션 {i+1} Bing+Sora 이미지 생성 실패 - 이미지 없음\n")
                # 실패 시 이미지 없음 (None 반환)
                return None
                
        except ImportError:
            print("⚠️ sora_bing_handler 모듈을 찾을 수 없습니다 - 이미지 없음")
            self.chat_log.append("⚠️ sora_bing_handler 모듈을 찾을 수 없습니다 - 이미지 없음\n")
            return None
        except Exception as e:
            print(f"⚠️ 섹션 {i+1} Bing+Sora 이미지 생성 중 오류: {e} - 이미지 없음")
            self.chat_log.append(f"⚠️ 섹션 {i+1} Bing+Sora 이미지 생성 중 오류: {e} - 이미지 없음\n")
            return None

    def insert_image_next_to_title(self, html, image_url, section_title):
        """이미지를 섹션 제목 옆에 삽입하는 함수"""
        try:
            # 이미지 URL 유효성 검사
            if not image_url or image_url.strip() == "":
                return html
            
            # h2 태그를 찾아서 이미지를 삽입
            if "<h2>" in html and "</h2>" in html:
                # h2 태그 다음에 이미지 삽입
                image_tag = f'<img src="{image_url}" style="width:100%;height:auto;margin:10px 0;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);" alt="{section_title} 이미지" />'
                modified_html = html.replace("</h2>", f"</h2>\n{image_tag}")
                return modified_html
            else:
                # h2 태그가 없으면 제목과 이미지를 함께 추가
                image_tag = f'<img src="{image_url}" style="width:100%;height:auto;margin:10px 0;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);" alt="{section_title} 이미지" />'
                return f"<h2>{section_title}</h2>\n{image_tag}\n{html}"
                
        except Exception as e:
            print(f"❌ 이미지 삽입 실패: {e}")
            return html  # 실패 시 원본 HTML 반환

    def create_section_html_without_image(self, section_data):
        """이미지 없이 섹션 HTML을 생성하는 함수"""
        section_title = section_data["section_title"]
        content = section_data["content"]
        
        # content에서 이미 h2 태그가 있는지 확인
        if "<h2>" in content:
            # 이미 제목이 있으면 그대로 사용
            return content
        else:
            # 제목이 없으면 추가
            html = f"<h2>{section_title}</h2>\n{content}\n"
            return html

    def create_section_html(self, section_data, image_url):
        """섹션 HTML을 생성하는 함수 (기존 호환성용)"""
        section_title = section_data["section_title"]
        content = section_data["content"]
        
        # 이미지 URL 유효성 검사
        if not image_url or image_url.strip() == "":
            image_url = None
        
        # content에서 이미 h2 태그가 있는지 확인
        if "<h2>" in content:
            # 이미 제목이 있으면 그대로 사용
            if image_url:
                # 쿠팡 이미지 모드이고 링크가 활성화되어 있으면 링크 추가
                image_mode = self.config.get("image_source", "bing")
                coupang_link_enabled = self.config.get("coupang_link_enabled", False)
                coupang_product = getattr(self, '_current_coupang_product', None)
                
                if image_mode == "coupang" and coupang_link_enabled and coupang_product:
                    product_url = coupang_product.get("url", coupang_product.get("link", coupang_product.get("product_url", "")))
                    if product_url:
                        # 이미지를 링크로 감싸기
                        img_tag = f'<a href="{product_url}" target="_blank" rel="noopener"><img src="{image_url}" style="width:100%;height:auto;margin:10px 0;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);cursor:pointer;" alt="{section_title} 이미지" /></a>'
                    else:
                        img_tag = f'<img src="{image_url}" style="width:100%;height:auto;margin:10px 0;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);" alt="{section_title} 이미지" />'
                else:
                    img_tag = f'<img src="{image_url}" style="width:100%;height:auto;margin:10px 0;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);" alt="{section_title} 이미지" />'
                
                content_with_image = content.replace("</h2>", f"</h2>\n{img_tag}")
                return content_with_image
            else:
                return content
        else:
            # 제목이 없으면 추가
            if image_url:
                # 쿠팡 이미지 모드이고 링크가 활성화되어 있으면 링크 추가
                image_mode = self.config.get("image_source", "bing")
                coupang_link_enabled = self.config.get("coupang_link_enabled", False)
                coupang_product = getattr(self, '_current_coupang_product', None)
                
                if image_mode == "coupang" and coupang_link_enabled and coupang_product:
                    product_url = coupang_product.get("url", coupang_product.get("link", coupang_product.get("product_url", "")))
                    if product_url:
                        # 이미지를 링크로 감싸기
                        img_tag = f'<a href="{product_url}" target="_blank" rel="noopener"><img src="{image_url}" style="width:100%;height:auto;margin:10px 0;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);cursor:pointer;" alt="{section_title} 이미지" /></a>'
                    else:
                        img_tag = f'<img src="{image_url}" style="width:100%;height:auto;margin:10px 0;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);" alt="{section_title} 이미지" />'
                else:
                    img_tag = f'<img src="{image_url}" style="width:100%;height:auto;margin:10px 0;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);" alt="{section_title} 이미지" />'
                
                html = f'<h2>{section_title}</h2>\n{img_tag}\n{content}\n'
            else:
                html = f"<h2>{section_title}</h2>\n{content}\n"
            return html

    def upload_to_naver(self, title, content, category, keyword):
        """네이버 블로그에 업로드하는 함수"""
        if not self.config["naver_enabled"]:
            return False
            
        self.chat_log.append("📝 네이버 블로그에 업로드 중...\n")
        print("📝 네이버 블로그에 업로드 중...")
        
        try:
            # naver_auto_writer 모듈 import 시도
            post_to_naver = None
            try:
                from naver_auto_writer import post_to_naver
                print("✅ naver_auto_writer 모듈 import 성공!")
            except ImportError as import_error:
                self.chat_log.append(f"⚠️ naver_auto_writer 모듈 import 실패: {import_error}\n")
                print(f"⚠️ naver_auto_writer 모듈 import 실패: {import_error}")
                print("⚠️ 대체 업로드 방법을 사용합니다.")
                post_to_naver = None
            
            # image_search 모듈 import 시도 (선택적)
            image_search_available = False
            try:
                import image_search
                image_search_available = True
                print("✅ image_search 모듈 import 성공!")
            except ImportError as import_error:
                print(f"⚠️ image_search 모듈 import 실패: {import_error}")
                print("⚠️ 이미지 검색 기능 없이 업로드를 진행합니다.")
                image_search_available = False

            naver_id = self.config.get("naver_id", "").strip()
            if not naver_id:
                self.chat_log.append("❌ 네이버 ID가 설정되지 않았습니다.\n")
                print("❌ 네이버 ID가 설정되지 않았습니다.")
                return False
            
            # 이미지 소스 설정에 따라 플래그 설정
            image_source = self.config.get("image_source", "bing")
            use_pinterest_image = (image_source == "pinterest")
            use_bing_image = (image_source == "bing" or image_source == "bing_sora" or image_source == "bing + sora")

            print(f"🔧 네이버 업로드 설정:")
            print(f"   - 네이버 ID: {naver_id}")
            print(f"   - 제목: {title}")
            print(f"   - 카테고리: {category}")
            print(f"   - 키워드: {keyword}")
            print(f"   - Pinterest 이미지: {use_pinterest_image}")
            print(f"   - Bing 이미지: {use_bing_image}")

            # bo_table과 ca_name 가져오기
            bo_table = getattr(self, 'bo_table_combo', None)
            ca_name = getattr(self, 'ca_name_combo', None)
            
            bo_table_value = bo_table.currentText() if bo_table else "free"
            ca_name_value = ca_name.currentText() if ca_name else "일반"
            
            print(f"🔧 카테고리 설정:")
            print(f"   - bo_table: {bo_table_value}")
            print(f"   - ca_name: {ca_name_value}")
            
            # 네이버 업로드용 키워드 길이 제한 (100자 내외)
            keyword_for_naver = keyword.strip()
            if len(keyword_for_naver) > 100:
                keyword_for_naver = keyword_for_naver[:100]
                self.chat_log.append(f"🔧 키워드가 100자를 초과하여 잘렸습니다: {keyword_for_naver}\n")
                print(f"🔧 키워드가 100자를 초과하여 잘렸습니다: {keyword_for_naver}")
            
            # 네이버 업로드 함수 호출 (ca_name 사용)
            if post_to_naver:
                print("🚀 post_to_naver 함수 호출 중...")
                uploaded_content = post_to_naver(
                    naver_id,
                    title,
                    content,
                    ca_name_value,  # category 대신 ca_name 사용
                    keyword_for_naver,
                    use_pinterest_image,
                    use_bing_image
                )

                if uploaded_content:
                    self.chat_log.append("✅ 네이버 블로그에 업로드 완료!\n")
                    print("✅ 네이버 블로그에 업로드 완료!")
                    print(f"📄 업로드된 내용 길이: {len(uploaded_content)}자")
                    return True
                else:
                    self.chat_log.append("❌ 네이버 블로그 업로드 실패\n")
                    print("❌ 네이버 블로그 업로드 실패")
                    return False
            else:
                # 대체 방법: 파일로 저장
                print("📁 대체 방법: 파일로 저장")
                try:
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"naver_upload_{timestamp}.html"
                    
                    # HTML 파일로 저장
                    html_content = f"""
                                    <!DOCTYPE html>
                                    <html>
                                    <head>
                                        <meta charset="UTF-8">
                                        <title>{title}</title>
                                    </head>
                                    <body>
                                        <h1>{title}</h1>
                                        <p><strong>카테고리:</strong> {ca_name_value}</p>
                                        <p><strong>키워드:</strong> {keyword_for_naver}</p>
                                        <hr>
                                        {content}
                                    </body>
                                    </html>
                                    """
                    
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    
                    self.chat_log.append(f"✅ 대체 업로드 완료: {filename}\n")
                    print(f"✅ 대체 업로드 완료: {filename}")
                    return True
                    
                except Exception as e:
                    self.chat_log.append(f"❌ 대체 업로드 실패: {str(e)}\n")
                    print(f"❌ 대체 업로드 실패: {str(e)}")
                    return False
                
        except Exception as e:
            self.chat_log.append(f"❌ 네이버 업로드 오류: {str(e)}\n")
            print(f"❌ 네이버 업로드 오류: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def save_to_mysql(self, title, content, category, keyword):
        """MySQL에 저장하는 함수 (전에 사용하던 단순한 버전)"""
        try:
            import pymysql
            from datetime import datetime
            
            # utf8mb4 사용: 이모지 포함 저장 (별도 제거 없음)
            clean_title = title
            clean_content = content
            clean_category = category
            clean_keyword = keyword
            
            # wr_1 컬럼은 25글자 이하로 제한
            if len(clean_keyword) > 25:
                clean_keyword = clean_keyword[:25]
                self.chat_log.append(f"🔧 키워드가 25글자를 초과하여 잘렸습니다: {clean_keyword}\n")
                print(f"🔧 키워드가 25글자를 초과하여 잘렸습니다: {clean_keyword}")
            
            # 이모지는 제거하지 않음 (utf8mb4 컬레이션에서 정상 저장)
            
            conn = pymysql.connect(
                host='203.245.9.72',
                user='dbghwns2',
                password='9497371',
                database='참소식.com',
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci',
                use_unicode=True,
                init_command='SET NAMES utf8mb4'
            )
            
            with conn.cursor() as cursor:
                sql = """
                    INSERT INTO g5_write_blog
                    (wr_subject, wr_content, ca_name, wr_name, wr_hit, wr_datetime,
                     wr_reply, wr_comment_reply, wr_option, wr_seo_title,
                     wr_link1, wr_link2, wr_link1_hit, wr_link2_hit,
                     wr_good, wr_nogood, mb_id, wr_password, wr_email, wr_homepage,
                     wr_file, wr_last, wr_ip, wr_facebook_user, wr_twitter_user,
                     wr_1, wr_2, wr_3, wr_4, wr_5, wr_6, wr_7, wr_8, wr_9, wr_10)
                    VALUES (%s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(sql, (
                    clean_title, clean_content, clean_category, "GPT", 1, now_str,
                    '', '', 'html1', clean_title,
                    '', '', 0, 0,
                    0, 0, 'gpt', 'pass', '', '',
                    0, now_str, '127.0.0.1', '', '',
                    clean_keyword, '', '', '', '', '', '', '', '', ''
                ))
            
            conn.commit()
            conn.close()
            self.chat_log.append("✅ MySQL 저장 완료\n")
            print("✅ MySQL 저장 완료")
            return True
            
        except Exception as e:
            self.chat_log.append(f"❌ MySQL 저장 오류: {str(e)}\n")
            print(f"❌ MySQL 저장 오류: {str(e)}")
            return False

    def send_to_gpt(self, keyword):
        """메인 GPT 글 생성 함수"""
        try:
            # 새로운 글 시작 시 사용된 미디어 URL 초기화
            try:
                from sora_bing_handler import reset_used_media_urls
                reset_used_media_urls()
                self.chat_log.append("🔄 새로운 글 시작 - 사용된 미디어 URL 초기화 완료\n")
                print("🔄 새로운 글 시작 - 사용된 미디어 URL 초기화 완료")
            except ImportError as e:
                print(f"⚠️ sora_bing_handler 모듈 import 실패: {e}")
            
            # 쿠팡 상품 옵션 확인 (자동 수집이 활성화되어 있으면 항상 사용)
            coupang_enabled = True  # 자동 수집 시 항상 쿠팡 상품 사용
            coupang_product = None
            product_keyword = keyword
            
            # 쿠팡 상품 자동 수집이 활성화되어 있거나 수동으로 쿠팡 상품을 사용하는 경우
            if coupang_enabled:
                # 쿠팡 상품 정보 가져오기
                coupang_product = self.get_random_coupang_product()
                # 현재 쿠팡 상품을 인스턴스 변수로 저장 (insert_image_next_to_title에서 사용)
                self._current_coupang_product = coupang_product
                if coupang_product:
                    # 상품명을 키워드로 사용
                    product_name = coupang_product.get("name", coupang_product.get("title", keyword))
                    product_keyword = product_name
                    self.chat_log.append(f"🛒 쿠팡 상품 정보 사용: {product_name}\n")
                    print(f"🛒 쿠팡 상품 정보 사용: {product_name}")
                else:
                    self.chat_log.append("⚠️ 쿠팡 상품을 찾을 수 없어 기본 키워드를 사용합니다.\n")
                    print("⚠️ 쿠팡 상품을 찾을 수 없어 기본 키워드를 사용합니다.")
            
            # 콘텐츠 타입 확인
            content_type = self.content_type_combo.currentText()
            
            # 모든 모드에서 웹 데이터 수집 수행 (블로그 모드와 동일한 구조)
            self.chat_log.append(f"🔍 {content_type} 모드 - 웹 데이터 수집을 시작합니다...\n")
            print(f"🔍 {content_type} 모드 - 웹 데이터 수집을 시작합니다...")
            
            try:
                import sys
                import os
                
                # web_search.py 모듈 사용 (크롬 드라이버 기반)
                try:
                    from blog_html_generator.web_search import collect_search_data as web_search_collect
                    from blog_html_generator.web_search import search_google, search_bing
                except ImportError:
                    # 상대 경로로 시도
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    web_search_path = os.path.join(current_dir, 'blog_html_generator')
                    sys.path.insert(0, web_search_path)
                    from web_search import collect_search_data as web_search_collect
                    from web_search import search_google, search_bing
                
                # GPT로 최적의 검색어 생성 (상품명 사용)
                search_keywords = self.generate_optimal_search_keywords_for_main(product_keyword)
                
                # web_search.py의 collect_search_data 함수로 데이터 수집 (크롬 드라이버 사용)
                self.chat_log.append(f"🔍 '{search_keywords}' 구글/빙 검색 중 (크롬 드라이버)...\n")
                print(f"🔍 '{search_keywords}' 구글/빙 검색 중 (크롬 드라이버)...")
                
                # URL도 함께 수집
                collected_data, urls = web_search_collect(search_keywords, max_results=10, return_urls=True)
                self.collected_urls = urls
                print(f"🔗 수집된 URL 목록: {urls}")
                
                if not collected_data or len(collected_data) < 100:
                    self.chat_log.append(f"⚠️ 웹 검색 데이터가 부족합니다: {len(collected_data) if collected_data else 0}자\n")
                    print(f"⚠️ 웹 검색 데이터가 부족합니다: {len(collected_data) if collected_data else 0}자")
                    collected_data = collected_data if collected_data else ""
                
                self.chat_log.append(f"✅ 웹 데이터 수집 완료: {len(collected_data)}자\n")
                print(f"✅ 웹 데이터 수집 완료: {len(collected_data)}자")
                print(f"📄 수집된 데이터 미리보기: {collected_data[:200]}...")
                
                # 수집된 데이터를 GPT로 정리
                if collected_data and len(collected_data) >= 100:
                    self.chat_log.append("🤖 수집된 데이터를 GPT로 정리합니다...\n")
                    print("🤖 수집된 데이터를 GPT로 정리합니다...")
                    organized_data = self.organize_collected_data_with_gpt(product_keyword, collected_data)
                    self.collected_web_data = organized_data  # 정리된 데이터 저장
                else:
                    organized_data = collected_data
                    self.collected_web_data = organized_data
                
                enhanced_keyword = product_keyword  # 상품명 사용
                clean_trimmed_text = product_keyword  # clean_trimmed_text 정의
                
            except ImportError as e:
                print(f"⚠️ web_search 모듈 import 실패: {e}")
                # fallback: generate_filepath 시도
                try:
                    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'core', 'collect'))
                    from generate_filepath import collect_trending_articles_as_text, bing_search_urls
                    search_keywords = self.generate_optimal_search_keywords_for_main(product_keyword)
                    collected_data, filename = collect_trending_articles_as_text(search_keywords)
                    try:
                        urls = bing_search_urls(search_keywords)
                        self.collected_urls = urls
                    except:
                        self.collected_urls = []
                    organized_data = self.organize_collected_data_with_gpt(product_keyword, collected_data)
                    self.collected_web_data = organized_data
                    enhanced_keyword = product_keyword
                    clean_trimmed_text = product_keyword
                except:
                    enhanced_keyword = product_keyword
                    collected_data = ""
                    clean_trimmed_text = product_keyword
            except Exception as e:
                print(f"❌ 웹 데이터 수집 실패: {e}")
                import traceback
                traceback.print_exc()
                enhanced_keyword = product_keyword
                collected_data = ""
                clean_trimmed_text = product_keyword
            
            self.chat_log.append("🤖 GPT에게 글 생성을 요청합니다...\n")
            print("🤖 GPT에게 글 생성을 요청합니다...")
            
            # 사용자 입력 프롬프트 가져오기
            user_prompt = self.input_box.text().strip()
            
            # 콘텐츠 타입에 따른 프롬프트 생성 (프롬프트 템플릿 사용)
            try:
                from prompt_templates import get_blog_prompt_template, get_novel_prompt_template
                
                if content_type == "소설":
                    # 소설용 프롬프트 템플릿 사용 (사용자 프롬프트 포함)
                    prompt = get_novel_prompt_template(product_keyword, clean_trimmed_text)
                    # 사용자 프롬프트가 있으면 추가
                    if user_prompt:
                        prompt += f"\n\n📝 **사용자 추가 요청사항**:\n{user_prompt}"
                else:
                    # 블로그용 프롬프트 템플릿 사용
                    prompt = get_blog_prompt_template(product_keyword, clean_trimmed_text)
                    
                    # 쿠팡 상품 정보가 있으면 프롬프트에 추가
                    if coupang_product:
                        product_name = coupang_product.get("name", coupang_product.get("title", ""))
                        product_url = coupang_product.get("url", coupang_product.get("link", coupang_product.get("product_url", "")))
                        product_image = coupang_product.get("image", coupang_product.get("image_url", coupang_product.get("thumbnail", "")))
                        product_description = coupang_product.get("description", coupang_product.get("desc", ""))
                        product_price = coupang_product.get("price", coupang_product.get("price_text", ""))
                        
                        coupang_info = f"""
🛒 **쿠팡 상품 정보**:
- 상품명: {product_name}
- 상품 링크: {product_url}
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
                # 프롬프트 템플릿 파일이 없을 경우 fallback
                if content_type == "소설":
                    # 소설용 기본 프롬프트
                    prompt = f"""
🎯 **소설 작성 요청 사항**:
사용자가 요청한 주제: "{product_keyword}"

이 주제를 바탕으로 창의적이고 매력적인 소설을 작성해주세요.

📖 **소설 작성 가이드라인**:
당신은 창의적이고 매력적인 소설을 작성하는 전문 작가입니다.

**소설 작성 요구사항:**
1. **주제**: {product_keyword}
2. **장르**: 사용자가 요청한 장르에 맞게 작성
3. **구조**: 인트로, 전개, 클라이맥스, 결말의 완전한 구조
4. **등장인물**: 매력적이고 입체적인 캐릭터
5. **설정**: 생생하고 몰입감 있는 배경과 분위기
6. **대화**: 자연스럽고 캐릭터의 성격을 드러내는 대화
7. **묘사**: 감각적이고 상세한 묘사로 독자의 몰입도 향상

**수집된 웹 데이터 활용:**
수집된 웹 데이터를 참고하여 현실적이고 신뢰할 수 있는 배경과 설정을 구축하되, 
창작적 자유를 유지하여 매력적인 스토리를 만들어주세요.

위 가이드라인에 따라 "{product_keyword}" 주제의 매력적인 소설을 작성해주세요.
"""
                    # 사용자 프롬프트가 있으면 추가
                    if user_prompt:
                        prompt += f"\n\n📝 **사용자 추가 요청사항**:\n{user_prompt}"
                else:
                    # 블로그용 기본 프롬프트
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
                    
                    # 쿠팡 상품 정보가 있으면 프롬프트에 추가
                    if coupang_product:
                        product_name = coupang_product.get("name", coupang_product.get("title", ""))
                        product_url = coupang_product.get("url", coupang_product.get("link", coupang_product.get("product_url", "")))
                        product_image = coupang_product.get("image", coupang_product.get("image_url", coupang_product.get("thumbnail", "")))
                        product_description = coupang_product.get("description", coupang_product.get("desc", ""))
                        product_price = coupang_product.get("price", coupang_product.get("price_text", ""))
                        
                        coupang_info = f"""
🛒 **쿠팡 상품 정보**:
- 상품명: {product_name}
- 상품 링크: {product_url}
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
            
            # 메인 글 구조는 JSON으로만 응답하도록 강제 지시 추가
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
                primary_model=self.config.get("chat_model", "gpt-5-mini"),
                temperature=1,
            )
            
            response_text = (response.choices[0].message.content or "").strip()
            if not response_text:
                # 응답이 빈 경우 재시도 (요약 지시 + JSON만 응답 강조)
                retry_prompt = "필수: 위 요구사항에 따라 JSON만 출력하세요. 설명 금지."
                response = self.call_chat_with_fallback(
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "user", "content": retry_prompt}
                    ],
                    primary_model=self.config.get("chat_model", "gpt-5-mini"),
                    temperature=1,
                )
                response_text = (response.choices[0].message.content or "").strip()
            self.chat_log.append(f"✅ GPT 응답 받음\n")
            print("✅ GPT 응답 받음")
            print(response_text)
            
            # 글 구조 파싱
            section_titles, final_title = self.parse_article_structure(response_text, product_keyword)
            
            # 제목과 카테고리 설정
            title = final_title
            keywords = [product_keyword]  # 상품명을 키워드로 사용
            
            # GPT로 카테고리 추천 받기
            try:
                # 카테고리 목록 정의
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
                
                # 카테고리 추천 프롬프트 생성
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
                
                # 추천된 카테고리가 유효한지 확인
                valid_ca_names = [item["ca_name"] for item in category_list]
                if recommended_category in valid_ca_names:
                    category = recommended_category
                    print(f"🤖 GPT 카테고리 추천: {category}")
                else:
                    category = "AMERICAAI"  # 기본값
                    print(f"⚠️ 추천된 카테고리가 유효하지 않음: {recommended_category}, 기본값 사용: {category}")
                    
            except Exception as e:
                category = "AMERICAAI"  # 기본값
                print(f"⚠️ 카테고리 추천 실패: {e}, 기본값 사용: {category}")
            
            self.chat_log.append(f"📝 제목: {title}\n")
            self.chat_log.append(f"📂 카테고리: {category}\n")
            self.chat_log.append(f"🏷️ 키워드: {', '.join(keywords)}\n")
            print(f"📝 제목: {title}")
            print(f"📂 카테고리: {category}")
            print(f"🏷️ 키워드: {', '.join(keywords)}")

            # 1단계: 모든 섹션 내용을 먼저 완성
            content_parts = []
            section_data_list = []  # 섹션 데이터 저장용
            previous_sections_content = ""  # 이전 섹션들의 내용을 누적
            
            for i, section_title in enumerate(section_titles):
                try:
                    # 섹션 내용 생성 (이전 섹션 내용 포함)
                    section_data = self.generate_section_content(section_title, final_title, keyword, clean_trimmed_text, i, previous_sections_content)
                    section_data_list.append(section_data)
                    
                    # 섹션 HTML 생성 (이미지 없이)
                    html = self.create_section_html_without_image(section_data)
                    content_parts.append(html)
                    
                    # 이전 섹션 내용에 현재 섹션 내용 추가 (다음 섹션을 위해)
                    if section_data and "content" in section_data:
                        current_section_text = section_data["content"]
                        # HTML 태그 제거하여 순수 텍스트만 추출
                        import re
                        clean_text = re.sub(r'<[^>]+>', '', current_section_text)
                        previous_sections_content += f"\n\n{clean_text}"
                    
                    print(f"✅ 섹션 {i+1} 내용 생성 완료")
                    print(f"📝 누적된 이전 내용 길이: {len(previous_sections_content)}자")
                except Exception as e:
                    print(f"❌ 섹션 {i+1} 내용 생성 실패: {e}")
                    # 기본 내용으로 대체
                    content_parts.append(f"<h2>{section_titles[i]}</h2>\n<p>이 섹션의 내용을 생성하는 중 오류가 발생했습니다.</p>")
                    section_data_list.append({"section_title": section_titles[i], "content": "오류 발생"})
            
            # 2단계: 섹션 내용을 토대로 이미지 프롬프트 생성 및 이미지 생성
            image_mode = self.config.get("image_source", "bing")
            if image_mode == "none":
                self.chat_log.append("🚫 이미지 생성 건너뜀 (옵션: none)\n")
                print("🚫 이미지 생성 건너뜀 (옵션: none)")
                image_urls = [None] * len(section_data_list)
            elif image_mode == "coupang":
                # 쿠팡 이미지 모드: 쿠팡 상품 이미지 사용 (첫 번째 섹션에만 1개)
                self.chat_log.append("🛒 쿠팡 상품 이미지 사용 모드 (첫 번째 섹션에만 1개)\n")
                print("🛒 쿠팡 상품 이미지 사용 모드 (첫 번째 섹션에만 1개)")
                image_urls = []
                if coupang_product:
                    product_image = coupang_product.get("image", coupang_product.get("image_url", coupang_product.get("thumbnail", "")))
                    # 첫 번째 섹션에만 쿠팡 상품 이미지 사용
                    for i in range(len(section_data_list)):
                        if i == 0:
                            # 첫 번째 섹션에만 이미지 사용
                            image_urls.append(product_image if product_image else None)
                            print(f"✅ 섹션 {i+1} 쿠팡 상품 이미지 적용")
                        else:
                            # 나머지 섹션은 이미지 없음
                            image_urls.append(None)
                else:
                    # 쿠팡 상품이 없으면 모든 섹션에 None
                    image_urls = [None] * len(section_data_list)
                    self.chat_log.append("⚠️ 쿠팡 상품 정보가 없어 이미지를 사용할 수 없습니다.\n")
                    print("⚠️ 쿠팡 상품 정보가 없어 이미지를 사용할 수 없습니다.")
            else:
                self.chat_log.append("🖼️ 섹션별 이미지 생성 시작...\n")
                print("🖼️ 섹션별 이미지 생성 시작...")
            
            if image_mode not in ["none", "coupang"]:
                image_urls = []
                for i, section_data in enumerate(section_data_list):
                    try:
                        # 섹션 내용을 토대로 이미지 프롬프트 생성
                        image_prompt = self.generate_image_prompt_from_content(section_data)
                        
                        # 이미지 생성
                        image_url = self.generate_section_image_with_prompt(section_data, image_prompt, i, section_titles)
                        image_urls.append(image_url)
                        
                        print(f"✅ 섹션 {i+1} 이미지 생성 완료 (이미지: {'있음' if image_url else '없음'})")
                    except Exception as e:
                        print(f"❌ 섹션 {i+1} 이미지 생성 실패: {e}")
                        image_urls.append(None)
            
            # 3단계: 이미지를 섹션 제목 옆에 삽입 (none 모드일 땐 그대로 사용)
            final_content_parts = []
            for i, (html, image_url) in enumerate(zip(content_parts, image_urls)):
                try:
                    if image_mode == "none":
                        final_content_parts.append(html)
                    else:
                        final_html = self.insert_image_next_to_title(html, image_url, section_titles[i])
                        final_content_parts.append(final_html)
                except Exception as e:
                    print(f"❌ 섹션 {i+1} 이미지 삽입 실패: {e}")
                    final_content_parts.append(html)  # 이미지 없이 원본 HTML 사용
            
            # 전체 내용 조합 후 링크/앵커 정리
            content = "\n\n".join(final_content_parts)
            content = self.sanitize_and_fix_links(content, coupang_product)
            
            # 쿠팡 상품 정보가 있으면 상품 이미지와 링크를 첫 번째 섹션에 추가
            # (coupang 이미지 모드가 아닐 때만 별도로 추가)
            coupang_image_enabled = self.config.get("coupang_image_enabled", False)
            coupang_link_enabled = self.config.get("coupang_link_enabled", False)
            
            if coupang_product and coupang_image_enabled and image_mode != "coupang":
                try:
                    # 링크 사용 여부에 따라 HTML 생성
                    ad_html = self.create_coupang_ad_image_html(coupang_product, use_link=coupang_link_enabled)
                    if ad_html:
                        # 첫 번째 섹션 다음에 상품 이미지 삽입
                        if len(final_content_parts) > 0:
                            # 첫 번째 섹션 다음에 상품 정보 삽입
                            first_section_end = final_content_parts[0].find("</h2>")
                            if first_section_end != -1:
                                # h2 태그 다음에 상품 정보 삽입
                                final_content_parts[0] = final_content_parts[0][:first_section_end+5] + "\n" + ad_html + "\n" + final_content_parts[0][first_section_end+5:]
                            else:
                                # h2 태그가 없으면 첫 번째 섹션 끝에 추가
                                final_content_parts[0] = final_content_parts[0] + "\n" + ad_html
                        else:
                            # 섹션이 없으면 맨 앞에 추가
                            content = ad_html + "\n\n" + content
                        
                        # content 재조합
                        content = "\n\n".join(final_content_parts)
                        self.chat_log.append("✅ 쿠팡 상품 이미지 추가 완료\n")
                        print("✅ 쿠팡 상품 이미지 추가 완료")
                except Exception as e:
                    print(f"⚠️ 쿠팡 상품 이미지 추가 실패: {e}")
                    self.chat_log.append(f"⚠️ 쿠팡 상품 이미지 추가 실패: {e}\n")
            
            self.chat_log.append(f"📄 내용 생성 완료: {len(content)}자\n")
            print(f"📄 내용 생성 완료: {len(content)}자")
            
            # 이미지 생성 완료 요약 (HTML에서 이미지 태그 개수로 계산)
            image_count = content.count('<img src=')
            total_sections = len(section_titles)
            if image_mode == "none":
                self.chat_log.append("🚫 이미지 생성 생략 모드 - 이미지 요약 생략\n")
                print("🚫 이미지 생성 생략 모드 - 이미지 요약 생략")
            else:
                self.chat_log.append(f"🖼️ 이미지 생성 완료: {image_count}/{total_sections} 섹션\n")
                print(f"🖼️ 이미지 생성 완료: {image_count}/{total_sections} 섹션")
            
            # 블로그 업로드
            if self.config["tistory_enabled"]:
                self.chat_log.append("📝 티스토리에 업로드 중...\n")
                print("📝 티스토리에 업로드 중...")
                # 여기에 티스토리 업로드 로직 추가
            
            # 네이버 업로드 및 MySQL 저장 시 keyword를 100자 내외로 제한
            safe_keyword = (keyword or "").strip()
            if len(safe_keyword) > 100:
                safe_keyword = safe_keyword[:100]

            # 네이버 업로드 (GPT 추천 카테고리 사용)
            self.upload_to_naver(title, content, category, safe_keyword)
            
            # MySQL 저장 (GPT 추천 카테고리 사용)
            self.save_to_mysql(title, content, category, safe_keyword)
            
            self.chat_log.append("✅ 글 생성 및 업로드 완료!\n")
            print("✅ 글 생성 및 업로드 완료!")
            
        except Exception as e:
            self.chat_log.append(f"❌ JSON 파싱 오류: {e}\n")
            print(f"❌ JSON 파싱 오류: {e}")

    def toggle_auto_trends(self, state):
        """자동 트렌드 수집 토글"""
        is_enabled = state == Qt.Checked
        self.config["auto_trends_enabled"] = is_enabled
        self.save_config()
        
        if is_enabled:
            self.chat_log.append("🔄 자동 트렌드 수집을 활성화합니다...\n")
            print("🔄 자동 트렌드 수집 활성화 요청")
            self.start_auto_trends()
        else:
            self.chat_log.append("⏹️ 자동 트렌드 수집을 비활성화합니다...\n")
            print("⏹️ 자동 트렌드 수집 비활성화 요청")
            self.stop_auto_trends()
    
    def start_auto_trends(self):
        """자동 트렌드 수집 시작"""
        try:
            # 기존 스레드가 있으면 정리
            if self.auto_trends_thread:
                self.auto_trends_thread.stop()
                self.auto_trends_thread.wait()
                self.auto_trends_thread = None
            
            # 새로운 스레드 생성 및 시작
            interval = self.config.get("trends_interval", 60)
            self.auto_trends_thread = GoogleTrendsAutoThread(interval)
            self.auto_trends_thread.trends_collected.connect(self.on_trends_collected)
            self.auto_trends_thread.status_updated.connect(self.on_auto_status_updated)
            self.auto_trends_thread.countdown_updated.connect(self.on_countdown_updated) # 카운트다운 시그널 연결
            self.auto_trends_thread.start()
            
            self.chat_log.append(f"🔄 자동 트렌드 수집이 시작되었습니다. (간격: {interval}분)\n")
            self.auto_status_label.setText("상태: 실행 중")
            self.auto_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            
            # 카운트다운이 시작되면 수동 업데이트는 건너뛰기
            print(f"🔄 스레드 시작됨 - 카운트다운이 자동으로 시작됩니다.")
            
            print(f"✅ 자동 트렌드 수집 스레드 시작됨 - 간격: {interval}분")
            
        except Exception as e:
            self.chat_log.append(f"❌ 자동 트렌드 수집 시작 실패: {str(e)}\n")
            print(f"❌ 자동 트렌드 수집 시작 실패: {str(e)}")
            self.auto_status_label.setText("상태: 오류 발생")
            self.auto_status_label.setStyleSheet("color: #F44336; font-weight: bold;")
    
    def stop_auto_trends(self):
        """자동 트렌드 수집 중지"""
        try:
            if self.auto_trends_thread:
                self.auto_trends_thread.stop()
                self.auto_trends_thread.wait()
                self.auto_trends_thread = None
                self.chat_log.append("⏹️ 자동 트렌드 수집이 중지되었습니다.\n")
                self.auto_status_label.setText("상태: 중지됨")
                self.auto_status_label.setStyleSheet("color: #F44336; font-weight: bold;")
                self.next_collection_label.setText("⏳ 다음 수집: --:--")
                print("✅ 자동 트렌드 수집 스레드 중지됨")
            else:
                self.chat_log.append("⚠️ 자동 트렌드 수집이 이미 중지되어 있습니다.\n")
                print("⚠️ 자동 트렌드 수집이 이미 중지되어 있습니다.")
        except Exception as e:
            self.chat_log.append(f"❌ 자동 트렌드 수집 중지 중 오류: {str(e)}\n")
            print(f"❌ 자동 트렌드 수집 중지 중 오류: {str(e)}")
    
    def update_trends_interval(self, value):
        """트렌드 수집 간격 업데이트"""
        self.config["trends_interval"] = value
        self.save_config()
        
        # 자동 수집이 활성화되어 있으면 스레드 재시작
        if self.auto_trends_thread and self.auto_trends_thread.is_running:
            self.chat_log.append(f"⏰ 트렌드 수집 간격이 {value}분으로 변경되어 스레드를 재시작합니다.\n")
            self.start_auto_trends()  # 스레드 재시작
        else:
            self.chat_log.append(f"⏰ 트렌드 수집 간격이 {value}분으로 설정되었습니다.\n")
        
        self.update_next_collection_time()
    
    def update_next_collection_time(self):
        """다음 수집 시간 업데이트"""
        try:
            print(f"🔍 update_next_collection_time 호출됨")
            print(f"   - auto_trends_thread 존재: {self.auto_trends_thread is not None}")
            
            if self.auto_trends_thread:
                print(f"   - is_running: {self.auto_trends_thread.is_running}")
                print(f"   - interval_minutes: {self.auto_trends_thread.interval_minutes}")
            
            # 카운트다운이 활성화되어 있으면 수동 업데이트 건너뛰기
            if (self.auto_trends_thread and 
                self.auto_trends_thread.is_running and 
                hasattr(self.auto_trends_thread, 'next_collection_time') and
                self.auto_trends_thread.next_collection_time):
                print(f"⏰ 카운트다운이 활성화되어 있어 수동 업데이트를 건너뜁니다.")
                return
            
            if self.auto_trends_thread and self.auto_trends_thread.is_running:
                # 첫 번째 수집은 5초 후, 이후는 설정된 간격마다
                if hasattr(self.auto_trends_thread, '_first_collection_done') and self.auto_trends_thread._first_collection_done:
                    # 첫 번째 수집 완료 후: 설정된 간격으로 계산
                    next_time = datetime.now() + timedelta(minutes=self.auto_trends_thread.interval_minutes)
                else:
                    # 첫 번째 수집 전: 5초 후로 계산
                    next_time = datetime.now() + timedelta(seconds=5)
                
                next_time_str = next_time.strftime('%H:%M')
                self.next_collection_label.setText(f"⏳ 다음 수집: {next_time_str}")
                print(f"⏰ 다음 수집 시간 업데이트: {next_time_str}")
                print(f"   - 현재 시간: {datetime.now().strftime('%H:%M:%S')}")
                print(f"   - 다음 수집: {next_time_str}")
                print(f"   - 첫 번째 수집 완료 여부: {getattr(self.auto_trends_thread, '_first_collection_done', False)}")
            else:
                self.next_collection_label.setText("⏳ 다음 수집: --:--")
                print(f"⏰ 스레드가 실행 중이 아니므로 '--:--'로 설정")
        except Exception as e:
            print(f"❌ 다음 수집 시간 업데이트 오류: {str(e)}")
            import traceback
            traceback.print_exc()
            self.next_collection_label.setText("⏳ 다음 수집: 오류")
    
    def on_trends_collected(self, trends):
        """자동 트렌드 수집 완료 시 호출"""
        self.chat_log.append(f"📊 자동 트렌드 수집 완료: {trends[:100]}...\n")
        # 자동 수집 시에도 입력란을 새로운 트렌드로 초기화
        self.keyword_input.clear()
        self.keyword_input.setPlainText(trends)
        self.chat_log.append("🔄 키워드 입력란이 새로운 트렌드로 자동 업데이트되었습니다.\n")
        
        # 자동 멀티검색 설정 확인
        auto_multi_search_enabled = self.config.get("auto_multi_search_enabled", True)
        
        if auto_multi_search_enabled:
            # 자동으로 멀티검색 실행
            self.chat_log.append("🚀 자동 트렌드 수집 완료로 인한 멀티검색 자동 실행...\n")
            print(f"🚀 자동 트렌드 수집 완료 후 멀티검색 자동 실행")
            
            # 잠시 대기 후 멀티검색 실행 (UI 업데이트를 위해)
            QTimer.singleShot(1000, self.auto_handle_multi_keyword_search)
        else:
            self.chat_log.append("⏹️ 자동 멀티검색이 비활성화되어 있어 수동 실행이 필요합니다.\n")
            print(f"⏹️ 자동 멀티검색이 비활성화되어 있어 수동 실행이 필요합니다.")
        
        print(f"🔄 트렌드 수집 완료 후 다음 수집 시간 업데이트 호출")
        # 카운트다운이 활성화되어 있으면 수동 업데이트 건너뛰기
        if (self.auto_trends_thread and 
            self.auto_trends_thread.is_running and 
            hasattr(self.auto_trends_thread, 'next_collection_time') and
            self.auto_trends_thread.next_collection_time):
            print(f"⏰ 카운트다운이 활성화되어 있어 수동 업데이트를 건너뜁니다.")
        else:
            # 수집 완료 후 잠시 대기 후 다음 수집 시간 업데이트
            QTimer.singleShot(500, self.update_next_collection_time)
    
    def auto_handle_multi_keyword_search(self):
        """자동 트렌드 수집 완료 후 자동으로 실행되는 멀티검색"""
        try:
            # 이미 실행 중이면 중복 실행 방지
            if getattr(self, 'is_running', False):
                print("⚠️ 기존 멀티검색이 실행 중입니다. 자동 실행을 건너뜁니다.")
                return
            keywords_text = self.keyword_input.toPlainText().strip()
            if not keywords_text:
                self.chat_log.append("❌ 자동 수집된 키워드가 없습니다.\n")
                print("❌ 자동 수집된 키워드가 없습니다.")
                return
            
            # 쉼표/개행/세미콜론 등 다양한 구분자 지원
            import re
            raw_list = re.split(r'[\n\r,;\t]+', keywords_text)
            seen = set()
            keywords = []
            for kw in raw_list:
                k = kw.strip()
                if not k or k in seen:
                    continue
                seen.add(k)
                keywords.append(k)
            
            self.chat_log.append(f"🔍 자동 멀티 검색 시작: {len(keywords)}개의 키워드\n")
            self.chat_log.append(f"📝 키워드: {', '.join(keywords)}\n")
            print(f"🔍 자동 멀티 검색 시작: {len(keywords)}개의 키워드")
            print(f"📝 키워드: {', '.join(keywords)}")
            
            # 설정 업데이트
            self.config["tistory_enabled"] = self.tistory_checkbox.isChecked()
            self.config["naver_enabled"] = self.naver_checkbox.isChecked()
            self.config["image_source"] = self.image_source_combo.currentText()
            self.config["ad_link"] = self.ad_link_input.text().strip()
            self.save_config()
            
            # 실행 상태 업데이트
            self.is_running = True
            self.pause_button.setEnabled(True)
            self.stop_button.setEnabled(True)
            self.multi_search_button.setEnabled(False)
            
            # 각 키워드에 대해 GPT로 글 생성
            for i, keyword in enumerate(keywords, 1):
                if self.should_stop:
                    break
                    
                while self.is_paused:
                    time.sleep(0.1)
                    if self.should_stop:
                        break
                
                self.chat_log.append(f"📝 [{i}/{len(keywords)}] 키워드 '{keyword}' 처리 중...\n")
                print(f"📝 [{i}/{len(keywords)}] 키워드 '{keyword}' 처리 중...")
                self.send_to_gpt(keyword)
                
                # 키워드 간 간격 (설정된 분 단위, 일시정지/중지 반영)
                if i < len(keywords) and not self.should_stop:
                    self.sleep_with_controls(minutes=self.config.get("post_interval_minutes", 1))
            
            # 실행 완료
            self.is_running = False
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.multi_search_button.setEnabled(True)
            self.chat_log.append("✅ 자동 멀티 검색 완료!\n")
            print("✅ 자동 멀티 검색 완료!")
            # 다음 수집 시간은 '멀티검색 완료' 시점부터 카운트다운 시작
            try:
                if self.auto_trends_thread:
                    self.auto_trends_thread.schedule_next_after_completion()
                    # 카운트다운 라벨 즉시 업데이트
                    QTimer.singleShot(100, self.update_next_collection_time)
            except Exception as sched_e:
                print(f"⚠️ 다음 수집 예약 실패: {sched_e}")
            
        except Exception as e:
            self.chat_log.append(f"❌ 자동 멀티 검색 중 오류: {str(e)}\n")
            print(f"❌ 자동 멀티 검색 중 오류: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def toggle_auto_coupang(self, state):
        """자동 쿠팡 상품 수집 토글"""
        is_enabled = state == Qt.Checked
        self.config["auto_coupang_enabled"] = is_enabled
        self.save_config()
        
        if is_enabled:
            self.chat_log.append("🔄 자동 쿠팡 상품 수집을 활성화합니다...\n")
            print("🔄 자동 쿠팡 상품 수집 활성화 요청")
            self.start_auto_coupang()
        else:
            self.chat_log.append("⏹️ 자동 쿠팡 상품 수집을 비활성화합니다...\n")
            print("⏹️ 자동 쿠팡 상품 수집 비활성화 요청")
            self.stop_auto_coupang()
    
    def start_auto_coupang(self):
        """자동 쿠팡 상품 수집 시작"""
        try:
            # 기존 스레드가 있으면 정리
            if self.auto_coupang_thread:
                self.auto_coupang_thread.stop()
                self.auto_coupang_thread.wait()
                self.auto_coupang_thread = None
            
            # 새로운 스레드 생성 및 시작
            interval = self.config.get("coupang_interval", 60)
            json_path = self.config.get("coupang_selected_json_path", 
                r"E:\Gif\www\참소식.com\gnuboard5.5.8.3.2\theme\nbBasic\parts\data\coupang-selected.json")
            self.auto_coupang_thread = CoupangProductAutoThread(interval, json_path)
            self.auto_coupang_thread.products_collected.connect(self.on_coupang_products_collected)
            self.auto_coupang_thread.status_updated.connect(self.on_coupang_auto_status_updated)
            self.auto_coupang_thread.countdown_updated.connect(self.on_coupang_countdown_updated)
            self.auto_coupang_thread.start()
            
            self.chat_log.append(f"🔄 자동 쿠팡 상품 수집이 시작되었습니다. (간격: {interval}분)\n")
            self.coupang_auto_status_label.setText("상태: 실행 중")
            self.coupang_auto_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            
            print(f"✅ 자동 쿠팡 상품 수집 스레드 시작됨 - 간격: {interval}분")
            
        except Exception as e:
            self.chat_log.append(f"❌ 자동 쿠팡 상품 수집 시작 실패: {str(e)}\n")
            print(f"❌ 자동 쿠팡 상품 수집 시작 실패: {str(e)}")
            self.coupang_auto_status_label.setText("상태: 오류 발생")
            self.coupang_auto_status_label.setStyleSheet("color: #F44336; font-weight: bold;")
    
    def stop_auto_coupang(self):
        """자동 쿠팡 상품 수집 중지"""
        try:
            if self.auto_coupang_thread:
                self.auto_coupang_thread.stop()
                self.auto_coupang_thread.wait()
                self.auto_coupang_thread = None
                self.chat_log.append("⏹️ 자동 쿠팡 상품 수집이 중지되었습니다.\n")
                self.coupang_auto_status_label.setText("상태: 중지됨")
                self.coupang_auto_status_label.setStyleSheet("color: #F44336; font-weight: bold;")
                self.next_coupang_collection_label.setText("⏳ 다음 수집: --:--")
                print("✅ 자동 쿠팡 상품 수집 스레드 중지됨")
            else:
                self.chat_log.append("⚠️ 자동 쿠팡 상품 수집이 이미 중지되어 있습니다.\n")
                print("⚠️ 자동 쿠팡 상품 수집이 이미 중지되어 있습니다.")
        except Exception as e:
            self.chat_log.append(f"❌ 자동 쿠팡 상품 수집 중지 중 오류: {str(e)}\n")
            print(f"❌ 자동 쿠팡 상품 수집 중지 중 오류: {str(e)}")
    
    def update_coupang_interval(self, value):
        """쿠팡 상품 수집 간격 업데이트"""
        self.config["coupang_interval"] = value
        self.save_config()
        
        # 자동 수집이 활성화되어 있으면 스레드 재시작
        if self.auto_coupang_thread and self.auto_coupang_thread.is_running:
            self.chat_log.append(f"⏰ 쿠팡 상품 수집 간격이 {value}분으로 변경되어 스레드를 재시작합니다.\n")
            self.start_auto_coupang()  # 스레드 재시작
        else:
            self.chat_log.append(f"⏰ 쿠팡 상품 수집 간격이 {value}분으로 설정되었습니다.\n")
        
        self.update_next_coupang_collection_time()
    
    def update_next_coupang_collection_time(self):
        """다음 쿠팡 상품 수집 시간 업데이트"""
        try:
            if self.auto_coupang_thread and self.auto_coupang_thread.is_running:
                if hasattr(self.auto_coupang_thread, '_first_collection_done') and self.auto_coupang_thread._first_collection_done:
                    next_time = datetime.now() + timedelta(minutes=self.auto_coupang_thread.interval_minutes)
                else:
                    next_time = datetime.now() + timedelta(seconds=5)
                
                next_time_str = next_time.strftime('%H:%M')
                self.next_coupang_collection_label.setText(f"⏳ 다음 수집: {next_time_str}")
            else:
                self.next_coupang_collection_label.setText("⏳ 다음 수집: --:--")
        except Exception as e:
            print(f"❌ 다음 쿠팡 상품 수집 시간 업데이트 오류: {str(e)}")
            self.next_coupang_collection_label.setText("⏳ 다음 수집: 오류")
    
    def on_coupang_products_collected(self, products_data):
        """자동 쿠팡 상품 수집 완료 시 호출"""
        product_count = len(products_data.get("selected", []))
        self.chat_log.append(f"🛒 자동 쿠팡 상품 수집 완료: {product_count}개 상품\n")
        print(f"🛒 자동 쿠팡 상품 수집 완료: {product_count}개 상품")
        
        # 다음 수집 시간 설정 (스레드에서 이미 설정했을 수 있음)
        if self.auto_coupang_thread:
            # 스레드가 다음 수집 시간을 설정했는지 확인
            if (hasattr(self.auto_coupang_thread, 'next_collection_time') and
                self.auto_coupang_thread.next_collection_time):
                print(f"⏰ 다음 수집 시간이 이미 설정됨: {self.auto_coupang_thread.next_collection_time}")
            else:
                # 다음 수집 시간 설정
                if hasattr(self.auto_coupang_thread, 'schedule_next_after_completion'):
                    self.auto_coupang_thread.schedule_next_after_completion()
                # 카운트다운 라벨 즉시 업데이트
                QTimer.singleShot(100, self.update_next_coupang_collection_time)
        
        # 자동 멀티검색 설정 확인
        auto_multi_search_enabled = self.config.get("auto_multi_search_enabled", True)
        
        if auto_multi_search_enabled and product_count > 0:
            # 수집된 상품들을 키워드로 변환하여 자동으로 글 작성
            self.chat_log.append(f"🚀 쿠팡 상품 수집 완료로 인한 자동 글 작성 시작...\n")
            print(f"🚀 쿠팡 상품 수집 완료 후 자동 글 작성 시작")
            
            # 상품명들을 키워드로 변환
            products = products_data.get("selected", [])
            keywords = []
            for product in products:
                product_name = product.get("name") or product.get("title") or product.get("productName", "")
                if product_name:
                    keywords.append(product_name)
            
            if keywords:
                # 키워드 입력란 업데이트
                self.keyword_input.clear()
                self.keyword_input.setPlainText("\n".join(keywords))
                self.chat_log.append(f"📝 {len(keywords)}개 상품명이 키워드 입력란에 설정되었습니다.\n")
                
                # 잠시 대기 후 멀티검색 실행 (UI 업데이트를 위해)
                QTimer.singleShot(2000, self.auto_handle_coupang_multi_keyword_search)
        else:
            if not auto_multi_search_enabled:
                self.chat_log.append("⏹️ 자동 멀티검색이 비활성화되어 있어 수동 실행이 필요합니다.\n")
                print(f"⏹️ 자동 멀티검색이 비활성화되어 있어 수동 실행이 필요합니다.")
            elif product_count == 0:
                self.chat_log.append("⚠️ 수집된 상품이 없어 자동 글 작성을 건너뜁니다.\n")
                print(f"⚠️ 수집된 상품이 없어 자동 글 작성을 건너뜁니다.")
    
    def auto_handle_coupang_multi_keyword_search(self):
        """쿠팡 상품 수집 완료 후 자동으로 실행되는 멀티검색"""
        try:
            # 이미 실행 중이면 중복 실행 방지
            if getattr(self, 'is_running', False):
                print("⚠️ 기존 멀티검색이 실행 중입니다. 자동 실행을 건너뜁니다.")
                return
            
            keywords_text = self.keyword_input.toPlainText().strip()
            if not keywords_text:
                self.chat_log.append("❌ 자동 수집된 상품 키워드가 없습니다.\n")
                print("❌ 자동 수집된 상품 키워드가 없습니다.")
                return
            
            # 개행으로 구분된 키워드 파싱
            import re
            raw_list = re.split(r'[\n\r]+', keywords_text)
            seen = set()
            keywords = []
            for kw in raw_list:
                k = kw.strip()
                if not k or k in seen:
                    continue
                seen.add(k)
                keywords.append(k)
            
            if not keywords:
                self.chat_log.append("❌ 유효한 키워드가 없습니다.\n")
                print("❌ 유효한 키워드가 없습니다.")
                return
            
            self.chat_log.append(f"🛒 쿠팡 상품 기반 자동 글 작성 시작: {len(keywords)}개 상품\n")
            self.chat_log.append(f"📝 상품: {', '.join(keywords[:5])}{'...' if len(keywords) > 5 else ''}\n")
            print(f"🛒 쿠팡 상품 기반 자동 글 작성 시작: {len(keywords)}개 상품")
            print(f"📝 상품: {', '.join(keywords[:5])}{'...' if len(keywords) > 5 else ''}")
            
            # 설정 업데이트
            self.config["tistory_enabled"] = self.tistory_checkbox.isChecked()
            self.config["naver_enabled"] = self.naver_checkbox.isChecked()
            self.config["image_source"] = self.image_source_combo.currentText()
            self.config["ad_link"] = self.ad_link_input.text().strip()
            # 쿠팡 상품 이미지 및 링크 설정은 이미 저장됨
            self.save_config()
            
            # 실행 상태 업데이트
            self.is_running = True
            self.pause_button.setEnabled(True)
            self.stop_button.setEnabled(True)
            self.multi_search_button.setEnabled(False)
            
            # 각 상품(키워드)에 대해 GPT로 글 생성
            for i, keyword in enumerate(keywords, 1):
                if self.should_stop:
                    break
                    
                while self.is_paused:
                    time.sleep(0.1)
                    if self.should_stop:
                        break
                
                self.chat_log.append(f"📝 [{i}/{len(keywords)}] 상품 '{keyword}' 글 작성 중...\n")
                print(f"📝 [{i}/{len(keywords)}] 상품 '{keyword}' 글 작성 중...")
                self.send_to_gpt(keyword)
                
                # 상품 간 간격 (설정된 분 단위, 일시정지/중지 반영)
                if i < len(keywords) and not self.should_stop:
                    self.sleep_with_controls(minutes=self.config.get("post_interval_minutes", 1))
            
            # 실행 완료
            self.is_running = False
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.multi_search_button.setEnabled(True)
            self.chat_log.append("✅ 쿠팡 상품 기반 글 작성 완료!\n")
            print("✅ 쿠팡 상품 기반 글 작성 완료!")
            
            # 다음 수집 시간은 '글 작성 완료' 시점부터 카운트다운 시작
            try:
                if self.auto_coupang_thread:
                    self.auto_coupang_thread.schedule_next_after_completion()
                    # 카운트다운 라벨 즉시 업데이트
                    QTimer.singleShot(100, self.update_next_coupang_collection_time)
            except Exception as sched_e:
                print(f"⚠️ 다음 수집 예약 실패: {sched_e}")
            
        except Exception as e:
            self.chat_log.append(f"❌ 쿠팡 상품 기반 자동 글 작성 중 오류: {str(e)}\n")
            print(f"❌ 쿠팡 상품 기반 자동 글 작성 중 오류: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # 오류 발생 시에도 실행 상태 복구
            self.is_running = False
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.multi_search_button.setEnabled(True)
    
    def on_coupang_auto_status_updated(self, status):
        """쿠팡 자동 수집 상태 업데이트"""
        self.coupang_auto_status_label.setText(status)
        if "실행 중" in status or "수집 중" in status:
            self.coupang_auto_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif "오류" in status or "실패" in status:
            self.coupang_auto_status_label.setStyleSheet("color: #F44336; font-weight: bold;")
        else:
            self.coupang_auto_status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
    
    def on_coupang_countdown_updated(self, countdown_text):
        """쿠팡 상품 수집 카운트다운 업데이트"""
        self.next_coupang_collection_label.setText(countdown_text)
    
    def on_auto_status_updated(self, status):
        """자동 트렌드 수집 상태 업데이트"""
        self.chat_log.append(f"🔄 {status}\n")
        print(f"🔄 자동 트렌드 상태 업데이트: {status}")
        
        if "완료" in status:
            self.auto_status_label.setText("상태: 수집 완료")
            self.auto_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif "오류" in status or "실패" in status:
            self.auto_status_label.setText("상태: 오류 발생")
            self.auto_status_label.setStyleSheet("color: #F44336; font-weight: bold;")
        elif "중지" in status:
            self.auto_status_label.setText("상태: 중지됨")
            self.auto_status_label.setStyleSheet("color: #F44336; font-weight: bold;")
        else:
            self.auto_status_label.setText("상태: 실행 중")
            self.auto_status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
    
    def on_countdown_updated(self, text):
        """카운트다운 텍스트 업데이트"""
        print(f"⏰ UI 카운트다운 업데이트: {text}")
        self.next_collection_label.setText(text)
        print(f"⏰ next_collection_label 텍스트 설정 완료: {text}")
    
    def build_section_prompt_with_web_data(self, section_title, final_title, keyword, clean_trimmed_text, collected_data, previous_content=""):
        """웹 수집 데이터를 포함한 섹션 프롬프트 생성"""
        
        # 사용자 요청 사항을 가장 중요하게 강조
        user_request_section = f"""
🎯 **사용자 요청 사항 (가장 중요)**:
사용자가 요청한 주제: "{keyword}"

이 요청 사항을 반드시 중심으로 하여 섹션을 작성해주세요.
사용자가 원하는 내용과 방향성을 정확히 파악하여 작성하세요.

📝 **기존 작성된 내용 (참고용)**:
{previous_content}

위 기존 내용을 참고하여 중복되지 않는 새로운 관점과 정보로 전개해주세요.
"""
        
        # 이전 내용이 있는 경우 간단한 컨텍스트 제공
        context_instruction = ""
        if previous_content and previous_content.strip():
            context_instruction = f"""
이전 내용: {previous_content[:500]}{'...' if len(previous_content) > 500 else ''}

위 내용을 바탕으로 자연스럽게 이어서 작성해주세요.
"""

        # 웹 수집 데이터를 간단하게 정리 (URL 포함)
        web_data_section = ""
        if collected_data["web_contents"]:
            web_data_section = "참고할 웹 정보:\n"
            for i, content in enumerate(collected_data["web_contents"][:2], 1):  # 상위 2개만 사용
                # 각 내용을 100자로 제한
                limited_content = content[:100] + "..." if len(content) > 100 else content
                web_data_section += f"{i}. {limited_content}\n"
        
        # 핵심 단어 링크 생성 (GPT가 본문에서 자동으로 링크 걸도록)
        url_section = ""
        if collected_data.get("urls"):
            url_section = "핵심 단어 링크 (본문에서 자동 적용):\n"
            
            # 섹션 제목과 키워드에서 핵심 단어 추출
            from urllib.parse import quote
            
            core_terms = []
            
            # 섹션 제목에서 핵심 단어 추출
            title_words = section_title.split()
            for word in title_words:
                if len(word) >= 2:  # 2글자 이상인 단어만
                    core_terms.append(word)
            
            # 키워드에서도 핵심 단어 추출
            keyword_words = keyword.split()
            for word in keyword_words:
                if len(word) >= 2 and word not in core_terms:
                    core_terms.append(word)
            
            # 상위 5개 핵심 단어에 대해 링크 정보 제공
            for i, term in enumerate(core_terms[:5], 1):
                # 본문 내용을 기반으로 의미있는 검색어 구성
                # 섹션 제목과 키워드를 조합하여 실제 내용에 맞는 검색어 생성
                
                # 섹션 제목에서 핵심 내용 추출
                section_keywords = []
                for word in section_title.split():
                    if len(word) >= 2 and word != term:
                        section_keywords.append(word)
                
                # 키워드에서도 추가 내용 추출
                keyword_parts = []
                for word in keyword.split():
                    if len(word) >= 2 and word != term:
                        keyword_parts.append(word)
                
                # 의미있는 검색어 조합
                search_components = [term]
                search_components.extend(section_keywords[:2])  # 섹션 제목에서 2개
                search_components.extend(keyword_parts[:2])     # 키워드에서 2개
                
                detailed_search = " ".join(search_components)
                
                # 10글자 이상 보장
                if len(detailed_search) < 10:
                    detailed_search = f"{term} {keyword} {section_title}"
                
                search_query = quote(detailed_search)
                # 설정에서 검색 엔진 가져오기
                search_engine = self.config.get("search_engine", "bing").lower()
                try:
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
- 최소 100자 이상으로 작성하여 충분한 상세함 제공
- 시각적 요소, 색상, 분위기, 스타일 등을 포함
- 예시: "현대적인 오피스에서 열심히 일하는 젊은 직장인들, 자연광이 들어오는 큰 창문, 깔끔한 책상과 노트북, 전문적이고 활기찬 분위기, 4K 고화질, 상세한 묘사"
"""

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = GPTChatUI()
    window.show()
    sys.exit(app.exec_())



# 애니메이션 스타일 변환 프롬프트는 prompt_templates.py에서 가져옴
try:
    from prompt_templates import get_anime_style_conversion_prompt
    ANIME_STYLE_CONVERSION_PROMPT = get_anime_style_conversion_prompt()
except ImportError:
    ANIME_STYLE_CONVERSION_PROMPT = """
당신은 한국 소설을 일본 애니메이션 스타일로 변환하는 전문가입니다. 
다음 지침에 따라 소설을 변환해주세요:

**스타일 변환 요소:**
1. **시각적 묘사 강화**: 애니메이션의 장면 전환과 카메라 워크를 고려한 구체적인 시각 묘사
2. **감정 표현의 과장**: 캐릭터의 내면 감정을 외적 행동과 표정으로 과장하여 표현
3. **대사 스타일**: 일본 애니메이션 특유의 감정적이고 직설적인 대사로 변환
4. **배경 음악 효과**: 장면의 분위기를 강조하는 음악적 요소 추가
5. **클라이맥스 강화**: 긴장감과 드라마틱한 요소를 극대화

**변환 규칙:**
- 한국어 원문의 핵심 스토리와 캐릭터는 유지
- 일본 애니메이션의 전형적인 표현 방식 적용
- 시청각적 요소를 강조한 서술로 변경
- 캐릭터의 감정선을 더욱 뚜렷하게 표현
- 장면 전환을 부드럽게 연결

**출력 형식:**
- 원문의 핵심 내용을 유지하면서 일본 애니메이션 스타일로 재구성
- 150글자 이상의 완성된 텍스트로 출력
- 자연스러운 한국어로 작성하되 애니메이션적 요소 포함

이제 주어진 한국 소설을 일본 애니메이션 스타일로 변환해주세요.
"""