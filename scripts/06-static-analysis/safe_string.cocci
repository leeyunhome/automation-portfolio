// =============================================================================
// safe_string.cocci — Coccinelle 시맨틱 패치
//
// 레거시 C 코드베이스 전체의 위험한 표준 함수 호출을
// 경계 검사가 들어간 래퍼(safe_*)로 일괄 치환한다.
//
// -----------------------------------------------------------------------------
// 왜 sed 가 아니라 Coccinelle 인가
// -----------------------------------------------------------------------------
// 텍스트 치환(sed/정규식)으로는 다음을 구분할 수 없다.
//   - 주석이나 문자열 리터럴 안의 "strcpy"
//   - my_strcpy_wrapper() 같은 부분 일치
//   - 매크로 정의부와 실제 호출부
//   - 인자 안에 괄호나 콤마가 중첩된 경우
//
// Coccinelle 은 C 파서 위에서 동작하므로 "함수 호출" 이라는 구문 구조를 인식한다.
// 또한 치환 결과에 sizeof(DST) 처럼 원래 인자에서 파생된 표현식을 넣을 수 있다.
// 이것은 텍스트 치환으로는 불가능하다.
//
// -----------------------------------------------------------------------------
// 치환 설계
// -----------------------------------------------------------------------------
// 래퍼 함수는 목적지 버퍼의 크기와 소스 길이를 함께 받아 런타임에 검증한다.
// 그 크기 정보를 호출 지점에서 sizeof(DST) / strlen(SRC) 로 자동 생성하는 것이
// 이 패치의 핵심이다. 사람이 수천 곳을 손으로 고치면 반드시 실수가 난다.
//
//   strcpy(dst, src)
//     -> safe_strcpy(NULL, NULL, sizeof(dst), strlen(src), dst, src)
//                                 ~~~~~~~~~~~~~~~~~~~~~~~~
//                                 호출 지점에서 자동 생성되는 경계 정보
//
// 앞의 NULL 두 개는 래퍼가 받는 (파일명, 함수명) 자리로,
// 위반 발생 시 로그에 위치를 남기기 위한 슬롯이다.
// (__FILE__, __func__ 로 채우면 추적성이 올라간다)
//
// -----------------------------------------------------------------------------
// 주의: sizeof(DST) 의 함정
// -----------------------------------------------------------------------------
// DST 가 배열이면 sizeof 는 버퍼 크기를 주지만,
// 포인터면 포인터 크기(4/8)를 준다.
// 따라서 이 패치는 "배열 버퍼로 선언된 목적지" 에 대해서만 안전하며,
// 적용 후 포인터 인자 호출부는 별도로 검토해야 한다.
// 자동화가 사람의 판단을 완전히 대체하지는 않는다는 뜻이다.
//
// -----------------------------------------------------------------------------
// 사용법
// -----------------------------------------------------------------------------
//   # 미리보기 (패치 파일만 생성, 원본 수정 없음)
//   spatch --sp-file safe_string.cocci --dir ./src > safe_string.patch
//
//   # 실제 적용
//   spatch --sp-file safe_string.cocci --dir ./src --in-place
//
//   # 특정 파일만
//   spatch --sp-file safe_string.cocci src/handler.c
// =============================================================================


// ---------------------------------------------------------------------------
// 포맷 문자열 계열
// ---------------------------------------------------------------------------

@@
expression DST, DST_SIZE;
expression list ARGS;
@@

- snprintf(DST, DST_SIZE, ARGS)
+ safe_snprintf(NULL, NULL, DST, DST_SIZE, ARGS)

// sprintf 는 크기 인자가 아예 없다 -> sizeof(DST) 를 주입해 경계를 부여한다
@@
expression DST;
expression list ARGS;
@@

- sprintf(DST, ARGS)
+ safe_sprintf(NULL, NULL, sizeof(DST), DST, ARGS)


// ---------------------------------------------------------------------------
// 문자열 복사 계열
// ---------------------------------------------------------------------------

// 목적지 크기와 소스 길이를 모두 주입 -> 래퍼가 양쪽을 대조 검증할 수 있다
@@
expression DST, SRC;
@@

- strcpy(DST, SRC)
+ safe_strcpy(NULL, NULL, sizeof(DST), strlen(SRC), DST, SRC)

// strncpy 는 널 종단을 보장하지 않는다 -> 래퍼에서 보장
@@
expression DST, SRC, COPY_SIZE;
@@

- strncpy(DST, SRC, COPY_SIZE)
+ safe_strncpy(NULL, NULL, sizeof(DST), DST, SRC, COPY_SIZE)

@@
expression DST, SRC, DST_SIZE;
@@

- strlcpy(DST, SRC, DST_SIZE)
+ safe_strlcpy(NULL, NULL, strlen(SRC), DST, SRC, DST_SIZE)


// ---------------------------------------------------------------------------
// 문자열 결합 계열
// ---------------------------------------------------------------------------

// 결합은 기존 내용 길이까지 고려해야 하므로 래퍼 내부에서 strlen(DST) 도 확인
@@
expression DST, SRC;
@@

- strcat(DST, SRC)
+ safe_strcat(NULL, NULL, sizeof(DST), strlen(SRC), DST, SRC)

@@
expression DST, SRC, MAX_APPEND;
@@

- strncat(DST, SRC, MAX_APPEND)
+ safe_strncat(NULL, NULL, sizeof(DST), DST, SRC, MAX_APPEND)


// ---------------------------------------------------------------------------
// 메모리 계열
// ---------------------------------------------------------------------------

@@
expression DST, SRC, COPY_SIZE;
@@

- memcpy(DST, SRC, COPY_SIZE)
+ safe_memcpy(NULL, NULL, sizeof(DST), DST, SRC, COPY_SIZE)

// 양쪽 버퍼 크기를 모두 넘겨 비교 길이가 어느 한쪽을 넘지 않는지 확인
@@
expression PTR1, PTR2, CMP_SIZE;
@@

- memcmp(PTR1, PTR2, CMP_SIZE)
+ safe_memcmp(sizeof(PTR1), sizeof(PTR2), PTR1, PTR2, CMP_SIZE)


// ---------------------------------------------------------------------------
// 할당 / 비교 계열
// ---------------------------------------------------------------------------

// 래퍼에서 반환값 NULL 검사와 크기 sanity check 를 수행한다
@@
expression SIZE;
@@

- malloc(SIZE)
+ safe_malloc(NULL, SIZE)

// NULL 포인터 방어를 래퍼로 위임
@@
expression STR1, STR2;
@@

- strcmp(STR1, STR2)
+ safe_strcmp(STR1, STR2)
