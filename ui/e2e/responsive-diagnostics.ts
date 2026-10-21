import type { Locator, Page } from "@playwright/test";

// Failure context only: preserve the existing viewport/visibility assertions.
export async function overflowDiagnostic(page: Page) {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    return {
      viewport: { width, height: document.documentElement.clientHeight, scrollWidth: document.documentElement.scrollWidth },
      elements: [...document.querySelectorAll<HTMLElement>("body *")]
        .filter((element) => element.getBoundingClientRect().right > width + 1)
        .slice(0, 30)
        .map((element) => {
          const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
          return {
            tag: element.tagName.toLowerCase(), className: element.className,
            text: element.textContent?.slice(0, 300), right: rect.right, width: rect.width, left: rect.left,
            font: style.font, whiteSpace: style.whiteSpace, overflowWrap: style.overflowWrap,
            display: style.display, position: style.position,
            parent: element.parentElement?.outerHTML.slice(0, 700),
          };
        }),
    };
  });
}

export async function visibilityDiagnostic(locator: Locator) {
  return locator.evaluateAll((elements) => elements.map((element) => {
    const ancestors = [];
    for (let node: Element | null = element; node && ancestors.length < 10; node = node.parentElement) {
      const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
      ancestors.push({
        tag: node.tagName.toLowerCase(), className: node.className,
        hidden: node.hasAttribute("hidden"), ariaHidden: node.getAttribute("aria-hidden"),
        open: node.tagName === "DETAILS" ? node.hasAttribute("open") : null,
        display: style.display, visibility: style.visibility, contentVisibility: style.contentVisibility,
        overflow: style.overflow, font: style.font, whiteSpace: style.whiteSpace,
        rect: { left: rect.left, right: rect.right, top: rect.top, width: rect.width, height: rect.height },
      });
    }
    return { text: element.textContent?.slice(0, 300), ancestors };
  }));
}
