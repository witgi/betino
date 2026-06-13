// Verejna konfiguracia pre front-end.
// POZOR: SUPABASE_KEY je "publishable/anon" kluc — je NAVRHNUTY ako verejny
// (je v kazdej klientskej appke). Data chrani RLS, nie utajenie tohto kluca.
// Tajny "service_role/secret" kluc sem NIKDY nepatri — ten ide len do GitHub secrets.
window.VB_CONFIG = {
  SUPABASE_URL: "https://xqkorhjywtrcdtcbugob.supabase.co",
  SUPABASE_KEY: "sb_publishable_ksoTZ_0VxO1AVMHiKzHJVw_BcNB7P_P",
};
