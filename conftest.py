"""conftest.py — pytest 공용 설정

앱 모듈(db_models 등)을 import 하면 SQLAlchemy 엔진이 USER_DATA_DIR 아래에
생성된다. 어떤 앱 모듈이 import 되기 전에 사용자 데이터 경로를 임시 폴더로
돌려 운영 DB/설정을 건드리지 않게 한다. 이 파일이 저장소 루트에 있으므로
pytest 가 루트를 sys.path 에 넣어 `import safe`, `import db_models` 가 풀린다.
"""
import os
from pathlib import Path

if not os.environ.get('MXF_QC_USER_DATA_DIR'):
    _root = Path(__file__).resolve().parent
    os.environ['MXF_QC_USER_DATA_DIR'] = str(_root / 'tmp' / 'pytest_user_data')
