// Service worker minimo - mantém extension viva
chrome.runtime.onInstalled.addListener(() => {
  console.log("PACTA Captura instalada");
});
