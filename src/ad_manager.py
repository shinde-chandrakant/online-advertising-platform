import sys
import json
import datetime
from datetime import datetime as dt
import mysql.connector
from pykafka import KafkaClient
from pykafka.common import OffsetType
from pykafka.exceptions import SocketDisconnectedError, LeaderNotAvailable

class KafkaMySQLSink:
    def __init__(self, kafka_bootstrap_server, kafka_topic_name, database_host,
database_username, database_password,database_name):
        # Initialize Kafka Consumer
        kafka_client = KafkaClient(kafka_bootstrap_server)
        self.consumer = kafka_client.topics[kafka_topic_name].get_simple_consumer(consumer_group="category",auto_offset_reset=OffsetType.LATEST)

        # Initialize MySQL database connection
        self.db = mysql.connector.connect(
        host=database_host,
        user=database_username,
        password=database_password,
        database=database_name
        )


    # Process single row
    def process_row(self, text, category, keywords, campaign_id, status, target_gender,
                 target_age_start, target_age_end, target_city, target_state,
                 target_country, target_income_bucket, target_device, cpc, cpa,
                 cpm, budget, current_slot_budget, date_range_start,
                 date_range_end, time_range_start, time_range_end):
        # Get the db cursor
        db_cursor = self.db.cursor()
        # DB query for supporting UPSERT operation
        sql = """
            INSERT INTO ads(
                text, category, keywords, campaign_id, status, target_gender,
                 target_age_start, target_age_end, target_city, target_state,
                 target_country, target_income_bucket, target_device, cpc, cpa,
                 cpm, budget, current_slot_budget, date_range_start,
                 date_range_end, time_range_start, time_range_end) 
                VALUES (
                    %s, %s, %s, %s, %s, %s, %d, %d, %s, %s, %s, %s, %s, %.2f, %.2f, %.2f, %.2f, %.2f, %s, %s, %s, %s)
                ON DUPLICATE KEY
                UPDATE text =%s, category =%s,keywords =%s,status =%s,targetGender =%s,targetAgeStart =%s,targetAgeEnd =%s,targetCity =%s,targetState =%s,targetCountry =%s,targetIncomeBucket =%s,targetDevice =%s,cpc =%s,cpa =%s,cpm =%s, budget =%s,currentSlotBudget =%s,dateRangeStart =%s, dateRangeEnd =%s,timeRangeStart =%s,timeRangeEnd =%s
        """
        val = (text, category, keywords, campaign_id, status, target_gender,
                 target_age_start, target_age_end, target_city, target_state,
                 target_country, target_income_bucket, target_device, cpc, cpa,
                 cpm, budget, current_slot_budget, date_range_start,
                 date_range_end, time_range_start, time_range_end)
        
        db_cursor.execute(sql, (val))
        # Commit the operation, so that it reflects globally
        self.db.commit()


    # Process kafka queue messages
    def process_events(self):

        def dervied_attribute(adInfo):

            def SlotBudgetCalculation(budget, date_range, time_range):
                Slotslist = []
                start = dt.strptime(date_range["start"]+" "+time_range["start"], "%Y-%m-%d %H:%M:%S")
                end = dt.strptime(date_range["end"]+" "+time_range["end"], "%Y-%m-%d %H:%M:%S")
                while start <= end:
                    Slotslist.append(start)
                    start += datetime.timedelta(minutes=10)
                return (float(budget)/len(Slotslist))

            # Setting derived Types like status,cpm,cuurent_slot_budget
            adInfo['status'] = "INACTIVE" if adInfo["action"] == "Stop Campaign" else "ACTIVE"
            adInfo["cpm"] = 0.0075 * float(adInfo["cpc"]) + 0.0005 * float(adInfo["cpa"])
            adInfo["current_slot_budget"] = SlotBudgetCalculation(adInfo["budget"],adInfo["date_range"],adInfo["time_range"])
            return adInfo

        try:
            for queue_message in self.consumer:
                if queue_message is not None:
                    msg = json.loads(queue_message.value())
                    AdsInfo = dervied_attribute(msg)
                    sep = " | "
                    print(AdsInfo["campaign_id"],sep,AdsInfo["action"],sep,AdsInfo["status"])
                    self.process_row(AdsInfo)

        # In case Kafka connection errors, restart consumer ans start processing
        except (SocketDisconnectedError, LeaderNotAvailable) as e:
            self.consumer.stop()
            self.consumer.start()
            self.process_events()


    def __del__(self):
        # Cleanup consumer and database connection before termination
        self.consumer.stop()
        self.db.close()



if __name__ == "__main__":
    # Validate Command line arguments
    if len(sys.argv) != 7:
        print("Usage: kafka_mysql.py <kafka_bootstrap_server> <kafka_topic> <database_host> ""<database_username> <database_password> <database_name>")
        exit(-1)

    kafka_bootstrap_server = sys.argv[1]
    kafka_topic = sys.argv[2]
    database_host = sys.argv[3]
    database_username = sys.argv[4]
    database_password = sys.argv[5]
    database_name = sys.argv[6]
    ad_manager = None


    try:
        kafka_mysql_sink = KafkaMySQLSink(kafka_bootstrap_server, kafka_topic,database_host, database_username,database_password, database_name)
        kafka_mysql_sink.process_events()
    except KeyboardInterrupt:
        print('KeyboardInterrupt, exiting...')
    finally:
        if kafka_mysql_sink is not None:
            del kafka_mysql_sink