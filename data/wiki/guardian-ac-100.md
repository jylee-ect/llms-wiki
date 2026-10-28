---
title: "가디언 AC-100"
type: "entity"
summary: "한빛시큐어가 출시한 기업용 출입통제 시스템으로 구역별 출입 권한을 관리한다."
sources: ["01_출입통제시스템_개요.md", "04_보안사고_대응절차.docx"]
updated: "2026-10-28"
---

가디언 AC-100은 한빛시큐어가 2024년에 출시한 기업용 출입통제 시스템이다. 사무실, 연구소, 데이터센터처럼 구역별 출입 권한을 달리해야 하는 사업장을 대상으로 하며, 문서 작성 시점 기준 전국 1,200여 개 사업장에 설치되어 있다. (출처: [[source-guardian-ac-100-overview]])

## 구성
시스템은 GR-200 리더기, GC-40 도어 컨트롤러, GMS 관리 서버, 웹 기반 관리 화면인 가디언 콘솔로 구성된다. (출처: [[source-guardian-ac-100-overview]])

## 기능과 연동
카드·얼굴·모바일 인증을 지원하며, 고보안 구역에는 카드와 얼굴을 조합한 2단계 인증을 권장한다. 출입 이벤트는 GMS에 기록되고, 비전 VMS와 연동해 특정 이벤트 발생 시 관련 카메라 영상을 관제 화면에 표시한다. (출처: [[source-guardian-ac-100-overview]])

## 사고 대응
AC-100 알람은 보안사고 탐지 경로 중 하나다. 사고가 탐지되면 관제 요원이 팝업 영상을 확인하고 등급을 판정하며, 사고 관련 GMS 출입 기록을 추출해 증거로 보존한다. (출처: [[source-security-incident-response-2026]])

## 관련 페이지
- 구성 요소: [[gc-40]], [[gr-200]], [[gms]]
- 통신 보안: [[osdp-v2]], [[tls-1-3]]
- 기록 및 영상 연동: [[access-event-records]], [[vision-vms-integration]]
- 사고 대응: [[security-incident-response]], [[security-evidence-preservation]]
