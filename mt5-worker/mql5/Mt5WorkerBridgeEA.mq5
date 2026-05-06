#property strict

#include <Trade/Trade.mqh>

input string ApiBase = "http://127.0.0.1:8780";
input string WorkerToken = "CHANGE_ME_LONG_RANDOM_TOKEN";
input string WorkerId = "macos-mt5-local-01";
input bool DryRun = true;
input long MagicNumber = 552501;
input int PollSeconds = 1;
input int HeartbeatSeconds = 10;
input int RequestTimeoutMs = 5000;
input bool UseConfigFile = true;
input string ConfigFileName = "mt5-worker.env";
input bool ConfigFileInCommon = true;

CTrade trade;
datetime g_last_heartbeat = 0;
string g_api_base = "";
string g_worker_token = "";
string g_worker_id = "";
bool g_dry_run = true;
long g_magic_number = 552501;
int g_poll_seconds = 1;
int g_heartbeat_seconds = 10;
int g_request_timeout_ms = 5000;

string Trim(string value)
  {
   return StringTrimLeft(StringTrimRight(value));
  }

string TrimRightSlash(string value)
  {
   int length = StringLen(value);
   while(length > 0 && StringGetCharacter(value, length - 1) == '/')
     {
      value = StringSubstr(value, 0, length - 1);
      length = StringLen(value);
     }
   return value;
  }

bool ParseBoolValue(string value, bool fallback)
  {
   string normalized = StringToLower(Trim(value));
   if(normalized == "true" || normalized == "1" || normalized == "yes" || normalized == "on")
      return true;
   if(normalized == "false" || normalized == "0" || normalized == "no" || normalized == "off")
      return false;
   return fallback;
  }

void ApplyConfigValue(string key, string value)
  {
   string normalized_key = StringToUpper(Trim(key));
   string normalized_value = Trim(value);

   if(normalized_key == "API_BASE" || normalized_key == "VPS_API_BASE")
      g_api_base = normalized_value;
   else if(normalized_key == "WORKER_TOKEN")
      g_worker_token = normalized_value;
   else if(normalized_key == "WORKER_ID")
      g_worker_id = normalized_value;
   else if(normalized_key == "DRY_RUN")
      g_dry_run = ParseBoolValue(normalized_value, g_dry_run);
   else if(normalized_key == "MT5_MAGIC" || normalized_key == "MAGIC_NUMBER")
      g_magic_number = (long)StringToInteger(normalized_value);
   else if(normalized_key == "POLL_SECONDS")
      g_poll_seconds = (int)StringToInteger(normalized_value);
   else if(normalized_key == "HEARTBEAT_SECONDS")
      g_heartbeat_seconds = (int)StringToInteger(normalized_value);
   else if(normalized_key == "REQUEST_TIMEOUT_MS")
      g_request_timeout_ms = (int)StringToInteger(normalized_value);
  }

void InitRuntimeConfig()
  {
   g_api_base = ApiBase;
   g_worker_token = WorkerToken;
   g_worker_id = WorkerId;
   g_dry_run = DryRun;
   g_magic_number = MagicNumber;
   g_poll_seconds = PollSeconds;
   g_heartbeat_seconds = HeartbeatSeconds;
   g_request_timeout_ms = RequestTimeoutMs;
  }

bool LoadConfigFile()
  {
   if(!UseConfigFile)
      return true;

   int flags = FILE_READ | FILE_TXT | FILE_ANSI;
   if(ConfigFileInCommon)
      flags |= FILE_COMMON;

   int handle = FileOpen(ConfigFileName, flags);
   if(handle == INVALID_HANDLE)
     {
      Print("Config file not loaded, using EA inputs. file=", ConfigFileName, " error=", GetLastError());
      return false;
     }

   while(!FileIsEnding(handle))
     {
      string line = Trim(FileReadString(handle));
      if(line == "" || StringSubstr(line, 0, 1) == "#")
         continue;

      int separator = StringFind(line, "=");
      if(separator <= 0)
         continue;

      string key = StringSubstr(line, 0, separator);
      string value = StringSubstr(line, separator + 1);
      ApplyConfigValue(key, value);
     }

   FileClose(handle);
   return true;
  }

bool HttpGet(string path, string &response, int &status)
  {
   string separator = StringFind(path, "?") >= 0 ? "&" : "?";
   string url = TrimRightSlash(g_api_base) + path + separator + "worker_token=" + UrlEncode(g_worker_token);
   string headers = "X-Worker-Token: " + g_worker_token + "\r\n";
   char data[];
   char result[];
   string result_headers;
   ResetLastError();
   status = WebRequest("GET", url, headers, g_request_timeout_ms, data, result, result_headers);
   if(status == -1)
     {
      Print("WebRequest failed: ", GetLastError(), " url=", url);
      return false;
     }
   response = CharArrayToString(result);
   return true;
  }

string UrlEncode(string value)
  {
   string encoded = "";
   for(int i = 0; i < StringLen(value); i++)
     {
      ushort c = StringGetCharacter(value, i);
      if((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~')
         encoded += ShortToString(c);
      else if(c == ' ')
         encoded += "%20";
      else
         encoded += StringFormat("%%%02X", c);
     }
  return encoded;
  }

string JsonEscape(string value)
  {
   string escaped = "";
   for(int i = 0; i < StringLen(value); i++)
     {
      ushort c = StringGetCharacter(value, i);
      if(c == '\\')
         escaped += "\\\\";
      else if(c == '"')
         escaped += "\\\"";
      else if(c == '\n')
         escaped += "\\n";
      else if(c == '\r')
         escaped += "\\r";
      else if(c == '\t')
         escaped += "\\t";
      else
         escaped += ShortToString(c);
     }
   return escaped;
  }

string BuildPositionsJson()
  {
   int total = PositionsTotal();
   string json = "[";
   bool first = true;

   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;

      string symbol = PositionGetString(POSITION_SYMBOL);
      long position_type = PositionGetInteger(POSITION_TYPE);
      string side = position_type == POSITION_TYPE_SELL ? "sell" : "buy";
      double lots = PositionGetDouble(POSITION_VOLUME);
      double entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
      double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
      double profit = PositionGetDouble(POSITION_PROFIT);
      double swap = PositionGetDouble(POSITION_SWAP);
      long opened_at = PositionGetInteger(POSITION_TIME);
      long magic = PositionGetInteger(POSITION_MAGIC);
      string comment = PositionGetString(POSITION_COMMENT);

      if(!first)
         json += ",";
      json += StringFormat(
         "{\"ticket\":%I64u,\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%s,\"entry_price\":%s,\"current_price\":%s,\"profit\":%s,\"swap\":%s,\"opened_at\":%I64d,\"magic\":%I64d,\"comment\":\"%s\"}",
         ticket,
         JsonEscape(symbol),
         side,
         DoubleToString(lots, 2),
         DoubleToString(entry_price, 8),
         DoubleToString(current_price, 8),
         DoubleToString(profit, 2),
         DoubleToString(swap, 2),
         opened_at,
         magic,
         JsonEscape(comment)
      );
      first = false;
     }

   json += "]";
   return json;
  }

bool SendHeartbeat()
  {
   string broker = AccountInfoString(ACCOUNT_SERVER);
   long login = (long)AccountInfoInteger(ACCOUNT_LOGIN);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int open_positions = PositionsTotal();
   string positions_json = BuildPositionsJson();
   string path = StringFormat(
      "/api/worker/heartbeat-ping?worker_id=%s&mt5_connected=true&account_login=%I64d&broker=%s&balance=%s&equity=%s&open_positions=%d&positions_json=%s",
      UrlEncode(g_worker_id),
      login,
      UrlEncode(broker),
      DoubleToString(balance, 2),
      DoubleToString(equity, 2),
      open_positions,
      UrlEncode(positions_json)
   );
   string response;
   int status;
   if(!HttpGet(path, response, status))
      return false;
   return status >= 200 && status < 300;
  }

bool ReportStatus(string signal_id, string status_value, string message, double lots = 0.0, string broker_order_id = "", double executed_price = 0.0)
  {
   string path = StringFormat(
      "/api/worker/execution-report-ping?signal_id=%s&worker_id=%s&status=%s&message=%s&lots=%s&broker_order_id=%s&executed_price=%s",
      UrlEncode(signal_id),
      UrlEncode(g_worker_id),
      UrlEncode(status_value),
      UrlEncode(message),
      DoubleToString(lots, 2),
      UrlEncode(broker_order_id),
      DoubleToString(executed_price, _Digits)
   );
   string response;
   int status;
   if(!HttpGet(path, response, status))
      return false;
   return status >= 200 && status < 300;
  }

bool ParseSignalLine(string line, string &signal_id, string &symbol, string &side, double &lots, double &stop_loss, double &take_profit)
  {
   string parts[];
   int count = StringSplit(line, '|', parts);
   if(count < 6)
      return false;

   signal_id = parts[0];
   symbol = parts[1];
   side = parts[2];
   lots = StringToDouble(parts[3]);
   stop_loss = parts[4] == "" ? 0.0 : StringToDouble(parts[4]);
   take_profit = parts[5] == "" ? 0.0 : StringToDouble(parts[5]);
   return signal_id != "" && symbol != "" && side != "" && lots > 0.0;
  }

void ExecuteSignal(string signal_id, string symbol, string side, double lots, double stop_loss, double take_profit)
  {
   Print("Received signal: id=", signal_id, " symbol=", symbol, " side=", side, " lots=", DoubleToString(lots, 2));

   if(g_dry_run)
     {
      Print("[DRY_RUN] Would execute signal ", signal_id, ": ", side, " ", DoubleToString(lots, 2), " ", symbol);
      ReportStatus(signal_id, "filled", "DRY_RUN accepted signal; no MT5 order sent", lots);
      return;
     }

   if(!SymbolSelect(symbol, true))
     {
      ReportStatus(signal_id, "rejected", "symbol_select failed", lots);
      return;
     }

   trade.SetExpertMagicNumber(g_magic_number);
   trade.SetDeviationInPoints(20);

   bool ok = false;
   if(StringCompare(side, "buy", false) == 0)
      ok = trade.Buy(lots, symbol, 0.0, stop_loss, take_profit, "vps_forex_brain");
   else
      ok = trade.Sell(lots, symbol, 0.0, stop_loss, take_profit, "vps_forex_brain");

   if(!ok)
     {
      string msg = trade.ResultRetcodeDescription();
      ReportStatus(signal_id, "rejected", msg, lots);
      Print("Trade failed: ", msg);
      return;
     }

   ReportStatus(
      signal_id,
      "filled",
      "MT5 order filled",
      lots,
      IntegerToString((int)trade.ResultOrder()),
      trade.ResultPrice()
   );
  }

void PollSignal()
  {
   string path = StringFormat("/api/worker/next-signal-plain?worker_id=%s", UrlEncode(g_worker_id));
   string response;
   int status;
   if(!HttpGet(path, response, status))
      return;
   if(status < 200 || status >= 300 || response == "")
      return;

   string signal_id, symbol, side;
   double lots = 0.0, stop_loss = 0.0, take_profit = 0.0;
   if(!ParseSignalLine(response, signal_id, symbol, side, lots, stop_loss, take_profit))
     {
      Print("Unable to parse signal payload: ", response);
      return;
     }
   ExecuteSignal(signal_id, symbol, side, lots, stop_loss, take_profit);
  }

int OnInit()
  {
   InitRuntimeConfig();
   LoadConfigFile();
   if(g_api_base == "" || g_worker_token == "" || g_worker_id == "")
     {
      Print("Missing required config values. ApiBase/WorkerToken/WorkerId must be set.");
      return(INIT_FAILED);
     }
   EventSetTimer(1);
   trade.SetExpertMagicNumber(g_magic_number);
   Print("Mt5WorkerBridgeEA started. WorkerId=", g_worker_id, " DryRun=", g_dry_run, " ApiBase=", g_api_base);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   datetime now = TimeCurrent();
   if(g_last_heartbeat == 0 || (now - g_last_heartbeat) >= g_heartbeat_seconds)
     {
      if(SendHeartbeat())
         g_last_heartbeat = now;
     }

   static datetime last_poll = 0;
   if(last_poll == 0 || (now - last_poll) >= g_poll_seconds)
     {
      PollSignal();
      last_poll = now;
     }
  }
