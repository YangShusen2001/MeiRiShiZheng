const siteUrl = process.env.PUBLIC_SITE_URL;
const apiUrl = process.env.PUBLIC_API_BASE;

if (!siteUrl || !apiUrl) {
  console.error("PUBLIC_SITE_URL and PUBLIC_API_BASE are required");
  process.exitCode = 2;
} else {
  const siteBase = new URL(siteUrl);
  const apiBase = new URL(apiUrl);
  const request = async (url, acceptedStatuses) => {
    const response = await fetch(url, {
      method: "GET",
      redirect: "follow",
      signal: AbortSignal.timeout(15_000),
    });
    if (!acceptedStatuses.includes(response.status)) {
      throw new Error(`${url.pathname} returned ${response.status}`);
    }
    return response;
  };

  const READER_LINK = /href=["']([^"']*\/read\/[^"'#?]+)["']/;
  const DAILY_LINK = /href=["']([^"']*\/daily\/[^"'#?/]+\/?)["']/;

  try {
    const home = await request(new URL("/", siteBase), [200]);
    const homeHtml = await home.text();

    // 首页的 /read/<id>/ 卡片来自 picks.json 的 picked，而管道在**零选日按设计不写
    // picks.json**（picked: [] 违反 schema 的 minItems: 1）—— 宁缺勿滥。
    // 所以「零选日的首页没有 reader 链接」是正确行为，不是部署故障。
    // 旧判据把它当失败，导致零选日必红；这里退回「首页最新的日报页」再取一次，
    // 日报页恒有 reader 链接，判据强度不变（仍然要求站点真的有可读内容）。
    let readerHref = homeHtml.match(READER_LINK)?.[1];
    let via = "home";
    if (!readerHref) {
      const dailyHref = homeHtml.match(DAILY_LINK)?.[1];
      if (!dailyHref) throw new Error("home page has no reader link and no daily link");
      const dailyUrl = new URL(dailyHref, siteBase);
      const daily = await request(dailyUrl, [200]);
      readerHref = (await daily.text()).match(READER_LINK)?.[1];
      via = `daily ${dailyUrl.pathname}`;
      if (!readerHref) throw new Error(`${via} has no reader link`);
    }
    await request(new URL(readerHref, siteBase), [200]);
    await request(new URL("/api/ping", apiBase), [200]);
    await request(new URL("/api/auth/session", apiBase), [200, 401]);
    await request(new URL("/api/subscription", apiBase), [200, 401]);
    console.log(`remote smoke passed: home, reader (via ${via}), API, auth, subscription`);
  } catch (error) {
    console.error(`remote smoke failed: ${error instanceof Error ? error.message : "UnknownError"}`);
    process.exitCode = 1;
  }
}
