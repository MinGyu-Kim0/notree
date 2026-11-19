<!-- 생성 파일: scripts/requirements_to_md.py로 시트에서 만든다. 직접 고치지 말 것. -->

# 요구사항 정의서

원본은 Google Sheet `1J7mkV8Ujdx-TgMfHclk2F0S-W5Cms609ruvDC8v8WCI`의 '요구사항 목록' 시트다. v0.4.5 · MVP 구현 착수 전 설계 변경 반영안 · '초기값'은 측정 전 정책 기준 · 비고의 [MVP]/[후속]은 출시 범위, '변경 제안(승인 대기)'는 미반영 · 구현·성능 검증 미실시

- 이 폴더는 시트에서 생성한 읽기용 사본이다. 요구사항을 바꿀 때는 시트를 고치고 다시 생성한다.
- 이 색인으로 필요한 ID를 찾은 뒤 해당 파일만 연다. 한 파일에 같은 영역의 요구사항이 모여 있다.
- 비고의 [MVP]/[후속]은 출시 범위, '초기값'은 측정 전 정책 기준이다. '변경 제안(승인 대기)'는 미반영이다.
- 요청자(전부 김민규 / 1조)와 요청일 열은 생략했다.

| ID | 요구사항명 | 우선순위 | 범위 | 담당 | 파일 |
|---|---|---|---|---|---|
| SFR-001 | 과목·강의 맥락 관리 | 필수 | MVP | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-002 | 녹음 시작·종료 | 필수 | MVP | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-003 | 일시정지·재개 | 권장 | MVP | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-004 | 한·영 혼합 실시간 전사 | 필수 | MVP | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-005 | 한·일 혼합 실시간 전사 | 선택 | 후속 | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-006 | 실시간 요약 노트 | 필수 | MVP | 이근욱 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-007 | 강의 최종 노트 | 필수 | MVP | 이근욱 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-008 | 과목별 종합 노트 | 필수 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-009 | 직접 작성·수정 | 필수 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-010 | 출처와 변경 이력 조회 | 필수 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-011 | 과목·강의 노트 조회 | 필수 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-012 | 강의 소속 이동 | 권장 | 후속 | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-013 | 노트 삭제 | 필수 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-014 | 학습 기록 내보내기 | 권장 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-015 | 완료 노트 재작성 | 권장 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-016 | 학습 맥락 기반 답변 | 필수 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-017 | 노트 반영 필요성 판단 | 필수 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-018 | 추가·수정·보완 구분 | 필수 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-019 | 반영 대상과 위치 결정 | 필수 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-020 | 정책에 따른 자율 반영 | 필수 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-021 | 처리 결과 구분 | 필수 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-022 | 사용자·Q&A 보완 보존 | 필수 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-023 | 검색·복습에 변경 전달 | 필수 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-024 | 학습 관찰 추출 | 필수 | MVP | 임서연 | [sfr-learner.md](sfr-learner.md) |
| SFR-025 | 근거에 따른 이해 상태 갱신 | 필수 | MVP | 임서연 | [sfr-learner.md](sfr-learner.md) |
| SFR-026 | Q&A·복습의 상태 공유 | 필수 | MVP | 임서연 | [sfr-learner.md](sfr-learner.md) |
| SFR-027 | 판단 확인·재평가 | 필수 | MVP | 임서연 | [sfr-learner.md](sfr-learner.md) |
| SFR-028 | 복습 개념 선택 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-029 | 문제 유형 선택 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-030 | 문제 난이도 조절 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-031 | 정보 부족 시 초기 복습 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-032 | 기본 망각 모델 적용 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-033 | 개인별 복습 시점 갱신 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-034 | 근거 있는 문제 생성 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-035 | 유형에 맞는 답안 평가 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-036 | 평가 결과의 후속 반영 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-037 | 복습 일정 보관·조회 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-038 | 예정 복습 제공 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-039 | 연기·건너뜀·미응답 처리 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-040 | 학습 가능 시간 반영 | 권장 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-041 | 변경된 자료의 복습 재검토 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-042 | 복습 선택 이유 안내 | 권장 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-043 | 실패한 생성 재시도 | 권장 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-044 | 로그인·로그아웃 | 필수 | MVP | 김민규 | [sfr-account.md](sfr-account.md) |
| SFR-045 | 계정 삭제 | 권장 | MVP | 김민규 | [sfr-account.md](sfr-account.md) |
| SFR-046 | 전사문 수정 | 권장 | MVP | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-047 | 노트 검색 | 권장 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-048 | 삭제 노트 복원 | 권장 | MVP | 이근욱 | [sfr-notes.md](sfr-notes.md) |
| SFR-049 | 자동 반영 변경 되돌리기 | 필수 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-050 | 보강 내용 표시 형태 | 권장 | MVP | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-051 | 보강 선호 반영 | 권장 | 후속 | 임서연 | [sfr-qa.md](sfr-qa.md) |
| SFR-052 | 복습 답안 제출 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-053 | 평가 피드백 제공 | 필수 | MVP | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-054 | 녹음 파일 업로드 | 선택 | 후속 | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-055 | 복습 일정 캘린더 등록 | 선택 | 후속 | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-056 | 복습 기록 시각화 | 선택 | 후속 | 임서연 | [sfr-review.md](sfr-review.md) |
| SFR-057 | 실시간 번역 표시 | 선택 | 후속 | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| SFR-058 | 오인식 의심 구간 수정 제안 | 권장 | MVP | 김민규 | [sfr-lecture.md](sfr-lecture.md) |
| DAR-001 | 자료별 상태와 맥락 보존 | 필수 | MVP | 김민규 | [data.md](data.md) |
| DAR-002 | 내용 식별과 버전 보존 | 필수 | MVP | 이근욱 | [data.md](data.md) |
| DAR-003 | 관찰과 이해 상태 분리 | 필수 | MVP | 임서연 | [data.md](data.md) |
| DAR-004 | 출제·평가·일정 연결 | 필수 | MVP | 임서연 | [data.md](data.md) |
| DAR-005 | 검색 자료 최신성 관리 | 필수 | MVP | 임서연 | [data.md](data.md) |
| DAR-006 | 삭제 영향 범위 관리 | 필수 | MVP | 김민규 | [data.md](data.md) |
| DAR-007 | 학습 자료 백업·복구 | 필수 | MVP | 김민규 | [data.md](data.md) |
| SER-001 | 질문 원문 보관 범위 | 필수 | MVP | 임서연 | [security.md](security.md) |
| SER-002 | 자료·상태 접근 통제 | 필수 | MVP | 김민규 | [security.md](security.md) |
| SER-003 | 외부 서비스 키 보호 | 필수 | MVP | 김민규 | [security.md](security.md) |
| SER-004 | 학습 데이터 전송 보호 | 필수 | MVP | 김민규 | [security.md](security.md) |
| QUR-001 | AI 판단 품질 검증 | 필수 | MVP | 전원 | [quality.md](quality.md) |
| QUR-002 | 최신 사용자 수정 보호 | 필수 | MVP | 이근욱 | [quality.md](quality.md) |
| QUR-003 | 연결 종료와 작업 상태 구분 | 필수 | MVP | 김민규 | [quality.md](quality.md) |
| QUR-004 | 재시도 시 중복 반영 방지 | 필수 | MVP | 김민규 | [quality.md](quality.md) |
| QUR-005 | 지원 환경의 학습 흐름 | 필수 | MVP | 전원 | [quality.md](quality.md) |
| QUR-006 | 개인맞춤 판단 평가 | 필수 | MVP | 임서연 | [quality.md](quality.md) |
| QUR-007 | 작업·AI 호출 추적 | 권장 | MVP | 김민규 | [quality.md](quality.md) |
| QUR-008 | 짧은 연결 끊김 시 음성 보존 | 권장 | MVP | 김민규 | [quality.md](quality.md) |
| PER-001 | 전사 표시 지연 기준 | 필수 | MVP | 김민규 | [performance.md](performance.md) |
| PER-002 | 최종 노트 생성 시간 기준 | 필수 | MVP | 이근욱 | [performance.md](performance.md) |
| PER-003 | 사용량·비용 한도 처리 | 필수 | MVP | 김민규 | [performance.md](performance.md) |
| PER-004 | Q&A 답변 응답 시간 기준 | 필수 | MVP | 임서연 | [performance.md](performance.md) |
| PER-005 | 복습 제공 지연 기준 | 필수 | MVP | 임서연 | [performance.md](performance.md) |
| SIR-001 | 음성 인식 실패 대응 | 필수 | MVP | 김민규 | [interface.md](interface.md) |
| SIR-002 | AI 응답 실패 대응 | 필수 | MVP | 김민규 | [interface.md](interface.md) |
| SIR-003 | 외부 AI 클라이언트 연동 | 선택 | 후속 | 김민규 | [interface.md](interface.md) |
| COR-001 | 서비스 실행 책임 분리 | 필수 | MVP | 김민규 | [constraints.md](constraints.md) |
| COR-002 | 기획 기술 구성 준수 | 필수 | MVP | 김민규 | [constraints.md](constraints.md) |
| COR-003 | 검사 후 수동 운영 배포 | 권장 | MVP | 김민규 | [constraints.md](constraints.md) |
| COR-004 | 강의 녹음 허락 확인 | 필수 | MVP | 전원 | [constraints.md](constraints.md) |
| COR-005 | 외부 AI 처리 고지·동의 | 필수 | MVP | 전원 | [constraints.md](constraints.md) |
