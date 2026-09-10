# Slide 5 샘플 생성 프롬프트

- 상태: 승인된 구성·스타일·백엔드에 따라 대표 샘플 한 장을 생성한 뒤, 사용자 요청 ‘각 서버가 별도 환경에서 실행 중이라고 가정’을 반영해 수정했다. 사용자가 이 수정본으로 전체 PPTX 제작을 승인했다. 최초 생성과 수정 프롬프트를 원래 파일명에 보관한다.
- 백엔드: built-in image tool, `image_gen__imagegen`
- 의도: 최초 `generate`, 현재 수정본 `edit`. 기존 샘플을 `view_image`로 확인한 뒤 `referenced_image_paths`로 전달해 동일 내장 도구에서 수정했다.
- 요청 비율: 16:9, 가로형. 구체 모델·품질 옵션은 도구가 노출하지 않아 별도 지정하지 않는다.
- 생성 결과: `origin_image/slide_05.png`, 1672×941 PNG. 원본 파일을 가공 없이 복사했다.

## 전달 프롬프트

Use case: productivity-visual.
Create exactly ONE complete finished Korean PowerPoint slide as one high-quality raster image. Landscape 16:9, ideally 2048×1152. It is a technical architecture presentation slide for the AI MAFIA project, not a website UI. All visible text must be accurately spelled in Korean and English as supplied below. Render clean, crisp Korean Gothic typography similar to Noto Sans KR, with very large bold title, readable body labels, and ample whitespace. Do not include a slide number, logo, watermark, invented metrics, or decorative mock UI.

Approved visual style: bright technology presentation. White or extremely pale lavender background, dark navy #17213C headings, purple #7357D8 accents, pale lavender #EEE8FB environment fills, gray #536079 supporting text. Precise thin orthogonal connectors, understated outline icons, subtly rounded environment boundaries, minimal shadows. One coherent spacious architecture composition, not a grid of dashboard cards. Five independent execution environment regions must be unmistakable. The central backend is visually strongest. The external LLM is a much smaller, muted, clearly external service and must not look like a sixth primary environment.

Title, large at top left, exact Korean: "다섯 시스템, 서로 다른 실행 환경"
Subtitle below, exact: "Frontend 2개 · Backend 1개 · MCP Server · DB Server"

Diagram layout: two frontends vertically stacked on the left; a tall backend region in the center; MCP upper right; database lower right. A small external LLM service above the central backend. Generous horizontal gaps between regions for labeled arrows. Keep all connectors outside text and icons. No lines between MCP and database. No lines between the two frontends. No line from MCP to LLM.

Five regions, exact text:
A, upper left: small "환경 A"; large "사용자 Front"; "Streamlit"; "게임 조작 · 상태 표시". A modest browser outline icon.
B, lower left: small "환경 B"; large "관리자 Front"; "Streamlit"; "운영 · 발언 분석". A modest analytics/browser outline icon.
C, center: small "환경 C"; large "Backend"; "FastAPI". Within this same environment show two clear inner modules labeled "Agent Orchestrator" and "Game Engine". Supporting line "판단 실행 · 규칙 검증".
D, upper right: small "환경 D"; large "MCP Server"; "FastMCP"; "Resource · Prompt · Tool". A modest connection outline icon.
E, lower right: small "환경 E"; large "DB Server"; "PostgreSQL"; "게임 상태 영구 저장". Below a thin internal separator, smaller "Redis: 공개 이력 캐시". A modest database cylinder outline icon. PostgreSQL is primary; Redis is auxiliary in this environment grouping.
External service above C: small unobtrusive cloud or outline shape with exact "외부 LLM". It sits outside all five environment boundaries.

Arrows are technically critical. Exactly these directed relationships:
1. A to C, label "HTTP API".
2. C back to A, separate dashed return arrow, label "sync / SSE". Keep direction clear and its label separate from HTTP API.
3. B to C, label "HTTP API".
4. C to D, label "Resource·Tool 요청".
5. D back to C, distinct parallel arrow, label "내부 HTTP API". These are two separate requests in opposite directions. Do not merge their arrowheads or labels.
6. C to E, label "저장·조회".
7. C upward to external LLM, label "모델 호출".
No other arrows. Ensure every arrowhead clearly touches its intended destination region boundary. MCP has no direct database or model access. Both inner backend modules remain inside environment C.

At the bottom, one short prominent takeaway sentence, exact: "서비스 주소를 연결하면 각 구성요소를 별도 환경에 배치할 수 있습니다."
This sentence is a claim about architectural capability, not evidence that five remote hosts were deployed. Keep it legible, with plenty of white space, separated from the main diagram by a very subtle horizontal rule if useful.

Design priority: viewers should immediately count five separate application/data environments, understand that Backend coordinates Agent and game rules, and distinguish Backend-to-MCP requests from MCP-to-Backend internal API requests. Prefer bigger readable labels over extra decoration. The whole slide must feel polished, calm, and suitable for a 15-minute Korean classroom project presentation.

## 수정 프롬프트 1

Use case: productivity-visual, edit of a complete Korean presentation slide.
Image 1 is the existing AI MAFIA architecture sample, the edit target. Preserve its bright white/lavender/navy visual style, readable Korean Gothic typography, five-region composition, internal backend modules, technology names, and all seven directed connections exactly. Keep the image landscape approximately 16:9. Make a focused revision to clarify this user-requested assumption: EACH OF THE FIVE SERVERS IS ALREADY RUNNING IN ITS OWN SEPARATE ENVIRONMENT. The image should show five independently running servers communicating over a network, rather than merely stating that separation is possible.

Change the title to this exact Korean text: "다섯 시스템, 다섯 개의 독립 서버".
Change the subtitle to this exact text: "분산 실행 가정 · Front 2개 · Backend · MCP · DB". The words "분산 실행 가정" must be clearly legible so the assumed deployment is not presented as a verified real deployment.

Transform each of the five environment outlines into an unmistakable separate host/server boundary with a simple server glyph in its header. Keep the same spatial placement and the original functional icons inside. Give each host its own compact header with an independent-environment label and a green status dot plus the words "실행 중". Green should be a very small status accent; the approved overall palette must remain white, lavender, and navy.
The five exact host headers are "서버 A · 독립 환경", "서버 B · 독립 환경", "서버 C · 독립 환경", "서버 D · 독립 환경", and "서버 E · 독립 환경". A and B contain their original user and admin frontends; C contains Backend, Agent Orchestrator, and Game Engine; D contains MCP Server; E contains PostgreSQL and the auxiliary Redis cache. The two backend modules must remain within ONE host, C. The external LLM remains small and separate above C, with no host A–E label or running indicator.

Replace the bottom takeaway with the exact sentence: "다섯 서버는 독립 환경에서 실행되며 네트워크로 통신합니다.".
Remove the previous wording about "배치할 수 있습니다". Do not add real or fictional IP addresses, domain names, provider logos, flags, locations, or performance numbers. The user supplied an architectural assumption only.

Preserve these directed arrows, their labels, and their endpoints with zero changes:
User Front to Backend: "HTTP API".
Backend to User Front: dashed "sync / SSE".
Admin Front to Backend: "HTTP API".
Backend to MCP: "Resource·Tool 요청".
MCP to Backend: "내부 HTTP API".
Backend to DB: "저장·조회".
Backend to external LLM: "모델 호출".
No extra arrows and no direct MCP-to-DB or MCP-to-LLM links. Preserve all original subsystem content and accurate Korean text. Adjust spacing slightly if needed to fit the new host headers and status indicators without crowding, truncation, overlaps, or shrinking important labels. No watermark, logo, page number, additional slide, or unrelated ornament.
