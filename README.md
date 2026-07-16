# 30gogo 투자관제실

## 실행 경계

- GitHub Pages는 암호화된 포트폴리오의 조회와 계산만 제공합니다.
- Mac 로컬 `http://127.0.0.1:4173`에서만 QQQ·SGOV 실제 매수 기능이 추가됩니다.
- 실제 주문 런타임과 증권사 자격정보는 이 저장소 밖에 있습니다.

## 모바일 잠금

Pages의 실제 데이터는 `portfolio.vault.json`에 `gzip + AES-256-GCM`으로 암호화되어 있습니다. 암호는 복호화에만 사용되며 서버로 전송되거나 브라우저 저장소에 저장되지 않습니다.

`이 기기에서 30일간 기억`을 선택하면 브라우저가 내보낼 수 없는 Web Crypto 키만 IndexedDB에 보관합니다. `이 기기 잠금`은 그 키를 즉시 삭제합니다.

모든 기억된 기기를 잠그려면 Mac에서 다음 명령을 실행해 암호와 데이터 키를 함께 교체합니다.

```bash
cd /Users/na/HermesProjects/30gogo-dashboard
node scripts/vault.mjs rotate-all
```

## Mac 로컬 실행

로컬 주문 서버는 macOS 로그인 시 자동으로 `127.0.0.1:4173`에만 열립니다.

```text
http://127.0.0.1:4173/#qqq
```

실제 주문은 다음 범위로 제한됩니다.

- QQQ·SGOV
- 미국 ETF 정수주 지정가 매수
- 1회 최대 $1,000
- 하루 최대 2건, 합계 $2,000
- 매도·시장가·소수점·자동주문·정정·취소 미지원

서버 시작 시 주문 기능은 잠겨 있습니다. 화면에서 10분 잠금을 해제한 뒤 사전점검, 확인문구, macOS 독립 확인창, 직전 재점검을 모두 통과해야 주문을 전송합니다.

## 시간별 동기화

Mac이 켜져 있으면 매시 정각에 다음 순서로 실행합니다.

1. Keychain의 자격정보로 Toss 읽기 전용 API를 조회합니다.
2. `~/.30gogo/data`의 개인 원본과 SQLite 이력을 갱신합니다.
3. 새 IV로 `portfolio.vault.json`을 다시 암호화합니다.
4. 보안 검사 통과 후 암호문 파일만 커밋·푸시합니다.

수동 실행:

```bash
/usr/bin/python3 toss_snapshot_sync.py
```

## 검증

```bash
node scripts/security-check.mjs
node --test tests/qqq-core.test.cjs
```

공개 파일에는 평문 자산 JSON, 증권사 토큰·계좌 식별자, 주문 endpoint, 외부 CDN 스크립트가 포함되면 안 됩니다.
