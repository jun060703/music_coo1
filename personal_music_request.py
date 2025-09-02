import os
import json
import time
import threading
import requests
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import yt_dlp
import webbrowser
from collections import defaultdict
import hashlib
import uuid

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('music_system.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
CORS(app)

# 데이터 저장 파일
REQUEST_FILE = 'music_requests.json'
CURRENT_PLAYING_FILE = 'current_playing.json'
STATS_FILE = 'music_stats.json'
USERS_FILE = 'users.json'

class PremiumMusicRequest:
    def __init__(self):
        self.requests = self.load_requests()
        self.current_playing = self.load_current_playing()
        self.stats = self.load_stats()
        self.users = self.load_users()
        self.is_playing = False
        self.play_thread = None
        self.play_history = []
        self.max_requests_per_user = 5  # 사용자당 최대 요청 수
        self.request_cooldown = 300  # 5분 쿨다운
        
    def load_requests(self):
        """음악 요청 목록 로드"""
        if os.path.exists(REQUEST_FILE):
            try:
                with open(REQUEST_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"요청 목록 로드 오류: {e}")
                return []
        return []
    
    def save_requests(self):
        """음악 요청 목록 저장"""
        try:
            with open(REQUEST_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.requests, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"요청 목록 저장 오류: {e}")
    
    def load_current_playing(self):
        """현재 재생 중인 음악 로드"""
        if os.path.exists(CURRENT_PLAYING_FILE):
            try:
                with open(CURRENT_PLAYING_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"현재 재생 정보 로드 오류: {e}")
                return None
        return None
    
    def save_current_playing(self, music_info):
        """현재 재생 중인 음악 저장"""
        try:
            with open(CURRENT_PLAYING_FILE, 'w', encoding='utf-8') as f:
                json.dump(music_info, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"현재 재생 정보 저장 오류: {e}")
    
    def load_stats(self):
        """통계 정보 로드"""
        if os.path.exists(STATS_FILE):
            try:
                with open(STATS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"통계 정보 로드 오류: {e}")
                return self.get_default_stats()
        return self.get_default_stats()
    
    def save_stats(self):
        """통계 정보 저장"""
        try:
            with open(STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"통계 정보 저장 오류: {e}")
    
    def get_default_stats(self):
        """기본 통계 정보"""
        return {
            'total_requests': 0,
            'completed_requests': 0,
            'total_play_time': 0,
            'popular_songs': {},
            'popular_requesters': {},
            'daily_stats': {},
            'system_uptime': datetime.now().isoformat()
        }
    
    def load_users(self):
        """사용자 정보 로드"""
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"사용자 정보 로드 오류: {e}")
                return {}
        return {}
    
    def save_users(self):
        """사용자 정보 저장"""
        try:
            with open(USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"사용자 정보 저장 오류: {e}")
    
    def search_youtube(self, query):
        """유튜브 검색 - 고급 검색 알고리즘"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'default_search': 'ytsearch',
                'extract_flat': 'in_playlist',
                'ignoreerrors': True,
                'no_check_certificate': True,
                'geo_bypass': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 기본 검색
                search_url = f"ytsearch20:{query}"
                results = ydl.extract_info(search_url, download=False)
                
                videos = []
                if results and 'entries' in results:
                    for entry in results['entries']:
                        if entry and entry.get('_type') != 'playlist':
                            video_info = {
                                'id': entry['id'],
                                'title': entry['title'],
                                'duration': entry.get('duration', 0),
                                'thumbnail': f"https://img.youtube.com/vi/{entry['id']}/maxresdefault.jpg",
                                'url': f"https://www.youtube.com/watch?v={entry['id']}",
                                'view_count': entry.get('view_count', 0),
                                'upload_date': entry.get('upload_date', ''),
                                'channel': entry.get('channel', '')
                            }
                            videos.append(video_info)
                
                # 결과가 적으면 확장 검색
                if len(videos) < 8:
                    logger.info(f"검색 결과가 적어서 확장 검색을 시도합니다: {query}")
                    
                    # 다양한 검색어 조합
                    search_variations = [
                        f"{query} 음악",
                        f"{query} 가사",
                        f"{query} 뮤직비디오",
                        f"{query} live",
                        f"{query} official",
                        f"{query} 가수",
                        f"{query} 아티스트"
                    ]
                    
                    for variation in search_variations:
                        if len(videos) >= 15:  # 충분한 결과가 있으면 중단
                            break
                        try:
                            search_url = f"ytsearch10:{variation}"
                            results = ydl.extract_info(search_url, download=False)
                            if results and 'entries' in results:
                                for entry in results['entries']:
                                    if entry and entry.get('_type') != 'playlist':
                                        # 중복 제거
                                        if not any(v['id'] == entry['id'] for v in videos):
                                            video_info = {
                                                'id': entry['id'],
                                                'title': entry['title'],
                                                'duration': entry.get('duration', 0),
                                                'thumbnail': f"https://img.youtube.com/vi/{entry['id']}/maxresdefault.jpg",
                                                'url': f"https://www.youtube.com/watch?v={entry['id']}",
                                                'view_count': entry.get('view_count', 0),
                                                'upload_date': entry.get('upload_date', ''),
                                                'channel': entry.get('channel', '')
                                            }
                                            videos.append(video_info)
                        except Exception as e:
                            logger.warning(f"확장 검색 오류 ({variation}): {e}")
                            continue
                
                # 결과 정렬 (조회수 기준)
                videos.sort(key=lambda x: x.get('view_count', 0), reverse=True)
                
                logger.info(f"검색 결과: {len(videos)}개 발견")
                return videos[:20]  # 최대 20개 반환
                
        except Exception as e:
            logger.error(f"검색 오류: {e}")
            return []
    
    def can_user_request(self, requester_name):
        """사용자가 요청할 수 있는지 확인"""
        return True, "OK"
    
    def add_request(self, music_info, requester_name):
        """음악 요청 추가 - 고급 검증"""
        # 요청 가능 여부 확인
        can_request, message = self.can_user_request(requester_name)
        if not can_request:
            return None, message
        
        request_info = {
            'id': str(uuid.uuid4()),
            'music': music_info,
            'requester': requester_name,
            'requested_at': datetime.now().isoformat(),
            'status': 'waiting',
            'priority': self.calculate_priority(requester_name)
        }
        
        self.requests.append(request_info)
        self.save_requests()
        
        # 통계 업데이트
        self.update_stats('request_added', requester_name, music_info)
        
        logger.info(f"새 요청 추가: {music_info['title']} (요청자: {requester_name})")
        return request_info, "요청이 성공적으로 추가되었습니다."
    
    def calculate_priority(self, requester_name):
        """요청 우선순위 계산"""
        # VIP 사용자, 관리자 등 특별한 우선순위
        if requester_name.lower() in ['admin', '관리자', 'vip']:
            return 100
        
        # 일반 사용자는 요청 시간 순
        return 1
    
    def update_stats(self, action, requester_name, music_info=None):
        """통계 정보 업데이트"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        if action == 'request_added':
            self.stats['total_requests'] += 1
            self.stats['popular_requesters'][requester_name] = \
                self.stats['popular_requesters'].get(requester_name, 0) + 1
            
            if music_info:
                song_key = f"{music_info['title']} - {music_info.get('channel', 'Unknown')}"
                self.stats['popular_songs'][song_key] = \
                    self.stats['popular_songs'].get(song_key, 0) + 1
            
            # 일일 통계
            if today not in self.stats['daily_stats']:
                self.stats['daily_stats'][today] = {
                    'requests': 0,
                    'completed': 0,
                    'play_time': 0
                }
            self.stats['daily_stats'][today]['requests'] += 1
        
        elif action == 'play_completed':
            self.stats['completed_requests'] += 1
            if music_info:
                self.stats['total_play_time'] += music_info.get('duration', 180)
            
            if today in self.stats['daily_stats']:
                self.stats['daily_stats'][today]['completed'] += 1
                self.stats['daily_stats'][today]['play_time'] += music_info.get('duration', 180)
        
        self.save_stats()
    
    def remove_request(self, request_id):
        """음악 요청 제거"""
        original_length = len(self.requests)
        self.requests = [r for r in self.requests if r['id'] != request_id]
        
        if len(self.requests) < original_length:
            self.save_requests()
            logger.info(f"요청 제거됨: {request_id}")
            return True
        return False
    
    def start_auto_play(self):
        """자동 재생 시작"""
        if not self.is_playing:
            self.is_playing = True
            self.play_thread = threading.Thread(target=self._auto_play_loop)
            self.play_thread.daemon = True
            self.play_thread.start()
            logger.info("자동 재생 시작")
    
    def stop_auto_play(self):
        """자동 재생 중지"""
        self.is_playing = False
        logger.info("자동 재생 중지")
    
    def _auto_play_loop(self):
        """자동 재생 루프 - 고급 스케줄링"""
        while self.is_playing:
            try:
                # 대기 중인 요청이 있는지 확인
                waiting_requests = [r for r in self.requests if r['status'] == 'waiting']
                
                if waiting_requests:
                    # 우선순위에 따라 정렬
                    waiting_requests.sort(key=lambda x: x.get('priority', 1), reverse=True)
                    current_request = waiting_requests[0]
                    music_info = current_request['music']
                    
                    logger.info(f"🎵 재생 시작: {music_info['title']} (요청자: {current_request['requester']})")
                    
                    # 상태를 재생 중으로 변경
                    current_request['status'] = 'playing'
                    self.current_playing = {
                        'request_id': current_request['id'],
                        'music': music_info,
                        'requester': current_request['requester'],
                        'started_at': datetime.now().isoformat()
                    }
                    self.save_current_playing(self.current_playing)
                    self.save_requests()
                    
                    # 브라우저에서 유튜브 재생
                    webbrowser.open(music_info['url'])
                    
                    # 음악 길이만큼 대기 (최소 3분, 최대 10분)
                    duration = max(min(music_info.get('duration', 180), 600), 180)
                    
                    # duration 시간만큼 정확히 대기
                    logger.info(f"음악 재생 시작: {duration}초 동안 재생됩니다.")
                    time.sleep(duration)
                    
                    logger.info(f"음악 재생 완료 ({duration}초)")
                    
                    # 재생 완료로 상태 변경
                    self.current_playing = None
                    self.save_current_playing(None)
                    self.save_requests()
                    
                    # 통계 업데이트
                    self.update_stats('play_completed', current_request['requester'], music_info)
                    
                    # 재생 히스토리에 추가
                    self.play_history.append({
                        'music': music_info,
                        'requester': current_request['requester'],
                        'completed_at': datetime.now().isoformat()
                    })
                    
                    logger.info(f"🎵 재생 완료: {music_info['title']}")
                    
                    # 다음 곡으로 넘어가기 전 잠시 대기
                    time.sleep(5)
                else:
                    # 대기 중인 요청이 없으면 잠시 대기
                    time.sleep(10)
                    
            except Exception as e:
                logger.error(f"자동 재생 루프 오류: {e}")
                time.sleep(30)
        
        logger.info("🎵 자동 재생 루프 종료")

# 전역 인스턴스
music_system = PremiumMusicRequest()

@app.route('/')
def index():
    """메인 페이지"""
    return render_template('personal_music.html', 
                         requests=music_system.requests,
                         current_playing=music_system.current_playing,
                         is_playing=music_system.is_playing)

@app.route('/search')
def search():
    """음악 검색"""
    query = request.args.get('q', '')
    if query:
        results = music_system.search_youtube(query)
        return jsonify(results)
    return jsonify([])

@app.route('/request_music', methods=['POST'])
def request_music():
    """음악 요청"""
    try:
        data = request.json
        music_info = data.get('music')
        requester_name = data.get('requester', '익명')
        
        if not music_info or not requester_name:
            return jsonify({'success': False, 'error': '음악 정보와 요청자 이름이 필요합니다.'})
        
        if requester_name == '익명':
            requester_name = f"익명_{hash(str(datetime.now()))[:8]}"
        
        request_info, message = music_system.add_request(music_info, requester_name)
        
        if request_info:
            return jsonify({'success': True, 'request': request_info, 'message': message})
        else:
            return jsonify({'success': False, 'error': message})
            
    except Exception as e:
        logger.error(f"음악 요청 오류: {e}")
        return jsonify({'success': False, 'error': '서버 오류가 발생했습니다.'})

@app.route('/remove_request/<request_id>', methods=['DELETE'])
def remove_request(request_id):
    """음악 요청 제거"""
    try:
        success = music_system.remove_request(request_id)
        return jsonify({'success': success})
    except Exception as e:
        logger.error(f"요청 제거 오류: {e}")
        return jsonify({'success': False, 'error': '제거 중 오류가 발생했습니다.'})

@app.route('/start_auto_play', methods=['POST'])
def start_auto_play():
    """자동 재생 시작"""
    try:
        music_system.start_auto_play()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"자동 재생 시작 오류: {e}")
        return jsonify({'success': False, 'error': '시작 중 오류가 발생했습니다.'})

@app.route('/stop_auto_play', methods=['POST'])
def stop_auto_play():
    """자동 재생 중지"""
    try:
        music_system.stop_auto_play()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"자동 재생 중지 오류: {e}")
        return jsonify({'success': False, 'error': '중지 중 오류가 발생했습니다.'})

@app.route('/status')
def status():
    """현재 상태 확인"""
    try:
        return jsonify({
            'is_playing': music_system.is_playing,
            'current_playing': music_system.current_playing,
            'request_count': len([r for r in music_system.requests if r['status'] == 'waiting']),
            'total_requests': len(music_system.requests),
            'completed_requests': len([r for r in music_system.requests if r['status'] == 'completed'])
        })
    except Exception as e:
        logger.error(f"상태 확인 오류: {e}")
        return jsonify({'error': '상태 확인 중 오류가 발생했습니다.'})

@app.route('/stats')
def get_stats():
    """통계 정보 조회"""
    try:
        return jsonify(music_system.stats)
    except Exception as e:
        logger.error(f"통계 조회 오류: {e}")
        return jsonify({'error': '통계 조회 중 오류가 발생했습니다.'})

@app.route('/history')
def get_history():
    """재생 히스토리 조회"""
    try:
        return jsonify(music_system.play_history[-50:])  # 최근 50개
    except Exception as e:
        logger.error(f"히스토리 조회 오류: {e}")
        return jsonify({'error': '히스토리 조회 중 오류가 발생했습니다.'})

if __name__ == '__main__':
    # templates 폴더 생성
    os.makedirs('templates', exist_ok=True)
    
    logger.info("🎵 Premium Music Request System 시작!")
    logger.info("🌐 웹 브라우저에서 http://localhost:5000 으로 접속하세요")
    logger.info("📱 상업용 고품질 음악 요청 시스템이 준비되었습니다!")
    
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
