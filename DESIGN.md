# Offer Calendar visual guide

## Overview

A light field notebook for an analyst reviewing observations in a daytime browser. Keep the calendar dense enough to scan a month, with a quiet header and an obvious path to the underlying text. The stylesheet lives in `apps/offer-calendar/styles.css`.

## Colors

Use warm paper and near-white surfaces, charcoal text, and one rust accent for supported change candidates and keyboard focus. CSS custom properties are the source of truth. Collection states always have text labels; color alone never conveys a result.

## Typography

Use the system sans-serif stack provided by Streamlit. A large project title establishes hierarchy; compact day labels and tabular date numerals make the calendar scannable. Original evidence has a more generous line height.

## Elevation

Flat surfaces and fine borders. A dark outline identifies the selected date. Avoid decorative shadows and animated page entrances.

## Components

Native radio buttons switch services and workspaces. The calendar scrolls inside its own region on narrow screens; it must not widen the page. Change details use a disclosure with before/after text. Missing captures have explicit text. Keyboard focus is visible on calendar links.

## Do's and Don'ts

- Keep the synthetic-data label visible in demo captures.
- Use actual rendered screenshots in documentation.
- Preserve incomplete and missing-source states.
- Avoid generic AI tool marketing, decorative KPI counters and invented accuracy claims.
