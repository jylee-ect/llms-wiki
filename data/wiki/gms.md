---
title: "GMS (Guardian Management Server)"
type: "entity"
summary: "AC-100의 권한 정책, 출입 기록 및 알람을 관리하는 서버."
sources: ["01_출입통제시스템_개요.md", "04_보안사고_대응절차.docx"]
updated: "2026-10-28"
---

GMS(Guardian Management Server)는 가디언 AC-100의 관리 서버로 권한 정책, 출입 기록, 알람을 관리한다. 성공·실패 출입, 강제 개방, 장시간 열림 등 출입 이벤트가 GMS에 기록된다. (출처: [[source-guardian-ac-100-overview]])

## 연동
강제 개방이나 출입 실패가 3회 이상 반복되면 GMS는 비전 VMS로 이벤트를 보내 해당 출입문 카메라 영상을 관제 화면에 팝업하도록 한다. (출처: [[source-guardian-ac-100-overview]])

## 사고 대응과 기록
보안사고 대응 시 관제 요원은 GMS 출입 기록을 추출해 사고 대장에 첨부한다. 출입 기록은 1년간 보관된다. (출처: [[source-security-incident-response-2026]])

## 관련 페이지
GMS는 [[guardian-ac-100]]의 구성 요소이며, 기록 정책은 [[access-event-records]], 사고 대응은 [[security-incident-response]], 영상 연동은 [[vision-vms-integration]]을 참고한다.
