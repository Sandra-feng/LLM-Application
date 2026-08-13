import time
import re

import psycopg2
from psycopg2 import sql
from typing import List, Tuple, Any, Iterator, Optional
import json
from pywin.Demos.dyndlg import test2

from base_configs.opengauss_config import OpengaussConfig
class OpenGaussUtil:
    def __init__(self):
        self.conn = psycopg2.connect(
            dbname=OpengaussConfig.Opengauss_DB,
            user=OpengaussConfig.Opengauss_USER,
            password=OpengaussConfig.Opengauss_PASS,
            host=OpengaussConfig.Opengauss_HOST,
            port=OpengaussConfig.Opengauss_PORT
        )
        self.cursor = self.conn.cursor()

        # 创建映射表
        self.keys = OpengaussConfig.DEFAULT_ALL_FIELDS
        self.map = {k: i for i, k in enumerate(self.keys)}
        print(self.map)
    def close(self):
        self.cursor.close()
        self.conn.close()

    def iterator_collection(self, batch_size: int, collection_name: str):
        """
        返回一个自定义迭代器，包含 next() 和 close()
        """

        class CollectionIterator:
            def __init__(self, cursor, collection_name, batch_size):
                self.cursor = cursor
                self.collection_name = collection_name
                self.batch_size = batch_size
                self.offset = 0
                self._closed = False

            def next(self):
                if self._closed:
                    return []

                self.cursor.execute(
                    sql.SQL("SELECT * FROM {} LIMIT %s OFFSET %s").format(
                        sql.Identifier(self.collection_name)
                    ),
                    (self.batch_size, self.offset)
                )
                rows = self.cursor.fetchall()

                if not rows:
                    return []

                colnames = [desc[0] for desc in self.cursor.description]
                result = [dict(zip(colnames, row)) for row in rows]
                self.offset += self.batch_size
                return result

            def close(self):
                self._closed = True

        return CollectionIterator(self.cursor, collection_name, batch_size)

    def query_by_condition_pagination(
        self,
        collection_name: str,
        search_condition: str = "",
        page: int = 1,
        page_size: int = 10,
        sort_field: str = "index",
        reverse: bool = True,
        content_filter: Optional[str] = None,
    ):
        """
        模拟 Milvus 的分页查询方法
        :return: (分页结果, 总条数)
        """
        assert page >= 1
        assert page_size > 0

        # 拼接 WHERE 子句
        where_clause = f"WHERE {search_condition}" if search_condition else ""

        # 先查出所有匹配数据（只查需要字段）
        self.cursor.execute(
            sql.SQL(f"""
                SELECT index, {sort_field}, content
                FROM {collection_name}
                {where_clause}
            """)
        )
        rows = self.cursor.fetchall()
        colnames = [desc[0] for desc in self.cursor.description]
        results = [dict(zip(colnames, row)) for row in rows]

        if content_filter:
            punctuation_pattern = re.compile(r"[^\w\s]", re.UNICODE)
            clean_filter = punctuation_pattern.sub("", content_filter).strip()
            if clean_filter:
                try:
                    pattern = re.compile(clean_filter, re.IGNORECASE)
                except re.error:
                    pattern = re.compile(re.escape(clean_filter), re.IGNORECASE)
                results = [
                    row
                    for row in results
                    if pattern.search(
                        punctuation_pattern.sub("", str(row.get("content") or ""))
                    )
                ]

        # 总条数
        total = len(results)

        # 排序
        results.sort(key=lambda x: x[sort_field], reverse=reverse)

        # 截取分页
        page_indices = results[(page - 1) * page_size: page * page_size] if page_size > 0 else results
        indices = [str(row["index"]) for row in page_indices]
        if not indices:
            return [], total

        # 再查一遍详细信息
        index_list_str = ",".join(indices)
        self.cursor.execute(
            sql.SQL(f"""
                SELECT *
                FROM {collection_name}
                WHERE index IN ({index_list_str})
            """)
        )
        full_rows = self.cursor.fetchall()
        full_colnames = [desc[0] for desc in self.cursor.description]
        final_result = [dict(zip(full_colnames, row)) for row in full_rows]

        return final_result, total

    def create_collection(self, collection_name: str, dim: int):
        self.cursor.execute(
            sql.SQL(
                "set enable_npu = on;"
            )
        )
        self.cursor.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS public.{table_name} "
                "(index BIGSERIAL PRIMARY KEY, "
                "file_name VARCHAR(65535),"
                "file_id VARCHAR(1000),"
                "file_time VARCHAR(65535),"
                "number BIGINT,"
                "content VARCHAR(65535),"
                "vector vector({dim}),"
                "question VARCHAR(65535),"
                "source_data JSONB)"

            ).format(
                table_name=sql.Identifier(collection_name),
                dim=sql.Literal(dim)
            )
        )
        self.cursor.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS vector ON public.{table_name} USING ivfflat (vector vector_l2_ops) WITH (lists = 128);"
            ).format(
                # index_name=sql.Identifier(index_name),
                table_name=sql.Identifier(collection_name)
            )
        )
        self.conn.commit()

    def drop_collection(self, collection_name: str):
        self.cursor.execute(
            sql.SQL("DROP TABLE IF EXISTS public.{table_name} CASCADE;")
            .format(table_name=sql.Identifier(collection_name))
        )
        self.conn.commit()

    def collection_is_exists(self, collection_name: str) -> bool:
        """
        判断指定 collection（表）是否已存在
        返回 True / False
        """
        self.cursor.execute(
            sql.SQL(
                "SELECT 1 "
                "FROM information_schema.tables "
                "WHERE table_schema = 'public' "
                "  AND table_name = %s"
            ),
            (collection_name,)  # 这里用 %s 占位即可，无需 sql.Identifier
        )
        return self.cursor.fetchone() is not None

    def del_document(self, collection_name: str, del_conditions: str = "") -> None:
        """
        根据传入的 WHERE 字符串删除文档
        空字符串 ⇒ 清空整张表（保留结构）
        """

        if del_conditions and del_conditions.strip():
            # 为了适配原来的那个milvus的条件匹配是 == 而mysql是 = 所以这里替换下
            del_conditions = del_conditions.replace("==","=")
            sql_cmd = sql.SQL(
                "DELETE FROM public.{table_name} WHERE {where_clause};"
            ).format(
                table_name=sql.Identifier(collection_name),
                where_clause=sql.SQL(del_conditions)  # 已拼好的条件直接嵌入
            )
        else:
            sql_cmd = sql.SQL(
                "TRUNCATE TABLE public.{table_name};"
            ).format(table_name=sql.Identifier(collection_name))

        self.cursor.execute(sql_cmd)
        self.conn.commit()

    def query_by_scalar(self, collection_name: str, query_conditions: str,
                        output_fields: list[str] = [],
                        limit: int | None = None
                        ) -> list[dict[str, Any]]:
        """
        根据标量进行查询
        :param collection_name: 知识库名称
        :param query_conditions: 查询条件
        :param output_fields: 输出字段列表
        :param limit: 限制返回条数
        :return: 查询结果列表
        """
        # 1. 处理列
        if output_fields:
            cols = sql.SQL(", ").join(sql.Identifier(c) for c in output_fields)
        else:
            cols = sql.SQL("*")

        # 2. 处理 WHERE 条件
        if query_conditions and query_conditions.strip():
            query_conditions = query_conditions.replace("==", "=")
            where_clause = sql.SQL("WHERE {}").format(sql.SQL(query_conditions))
        else:
            where_clause = sql.SQL("")

        # 3. 处理 LIMIT
        if limit:
            limit_clause = sql.SQL("LIMIT {}").format(sql.Literal(limit))
        else:
            limit_clause = sql.SQL("")

        # 4. 构建完整的SQL查询 - 关键修复点
        sql_cmd = sql.SQL("SELECT {} FROM {} {} {}").format(
            cols,
            sql.Identifier("public", collection_name),  # 使用schema.table格式
            where_clause,
            limit_clause
        )

        try:
            self.cursor.execute(sql_cmd)
            rows = self.cursor.fetchall()

            # 5. 获取列名
            if output_fields:
                keys = output_fields
            else:
                keys = [desc[0] for desc in self.cursor.description]

            return [dict(zip(keys, row)) for row in rows]

        except Exception as e:
            raise

    import json
    from typing import List, Any
    from psycopg2 import sql

    def add_document(self, collection_name: str, data: List[dict[Any]]):
        keys = ("file_name", "file_id", "file_time", "number", "content", "vector", "question", "source_data")

        rows = []
        for d in data:
            row = []
            for k in keys:
                if k == "source_data":
                    value = d.get(k, {})  # 默认是空字典
                    value = json.dumps(value)  # 转为 JSON 字符串
                else:
                    value = d.get(k, None)  # 其他字段默认 None
                row.append(value)
            rows.append(tuple(row))

        self.cursor.executemany(
            sql.SQL(
                "INSERT INTO public.{table_name} "
                "(file_name, file_id, file_time, number, content, vector, question, source_data) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s);"
            ).format(table_name=sql.Identifier(collection_name)),
            rows
        )
        self.conn.commit()

    def update_document(self, collection_name: str, data: List[dict[Any]]):
        item = data[0]
        index = item["index"]
        set_clauses = []
        values = []

        for key, value in item.items():
            set_clauses.append(f"{key} = %s")
            values.append(value)

        # 构建SQL语句
        set_clause = ", ".join(set_clauses)
        values.append(index)  # WHERE条件的值

        sql_query = sql.SQL(
            "UPDATE public.{table_name} SET {set_clause} WHERE index = %s;"
        ).format(
            table_name=sql.Identifier(collection_name),
            set_clause=sql.SQL(set_clause)
        )

        self.cursor.execute(sql_query, values)
        self.conn.commit()

    def search_by_vector(self, collection_name: str, vector: List[List[float]], limit: int, filter: str = "") -> List[
        dict[Any]]:
        docs = []

        for emb in vector:
            # 构建基础SQL
            base_sql = "SELECT *, vector <-> %s::vector AS score FROM public.{table_name}"

            # 处理过滤条件
            if filter and filter.strip():
                # 清理和转换过滤条件
                cleaned_filter = filter.replace("==", "=").replace('"', "'")
                where_clause = f" WHERE {cleaned_filter}"
            else:
                where_clause = ""

            # 完整的SQL语句
            full_sql = base_sql + where_clause + " ORDER BY score ASC LIMIT %s;"

            self.cursor.execute(
                sql.SQL(full_sql).format(table_name=sql.Identifier(collection_name)),
                (emb, limit)
            )
            self.conn.commit()
            result = self.cursor.fetchall()
            for row in result:
                data = {}
                for field in self.keys:
                    data[field] = row[self.map[field]]
                docs.append(data)
        docs =[docs]
        return docs  # 注意：这里应该返回docs而不是[docs]

    def rename_collection(self, old_name: str, new_name: str):
        """
        重命名集合（表）
        :param old_name: 旧表名
        :param new_name: 新表名
        :return: 是否成功
        """
        # 使用RENAME TABLE（推荐）
        sql_query = "RENAME TABLE `{}` TO `{}`".format(old_name, new_name)
        self.cursor.execute(sql_query)
        self.conn.commit()  # 确保提交事务





if __name__ == '__main__':
    opengauss = OpenGaussUtil()
    opengauss.create_collection(collection_name="testpy",dim=1024)
    from base_utils.embedding_util import *
    embedding = EmbeddingUtil(embedding_id="67e4f62c3119180a08d363ab")
    # result, total = opengauss.query_by_condition_pagination(collection_name="test789",
    #                                                         search_condition="file_name LIKE '3.docx'",
    #                                                         page=1,
    #                                                         page_size=4,
    #                                                         sort_field="file_time",
    #                                                         reverse=True)
    # print(result,total)
    # content = [
    #     "中国的主要节日包括春节、清明节、端午节和中秋节。春节是中国最重要的传统节日，家家户户都会庆祝。",
    #     "春节通常在农历正月初一庆祝，是中国人团聚和庆祝新年的重要时刻。人们会吃饺子、放鞭炮，并进行各种传统活动。",
    #     "中秋节是中国的传统节日，通常在农历八月十五庆祝。人们会吃月饼，赏月，庆祝丰收和家庭团聚。",
    #     "清明节是中国的传统节日之一，主要用于扫墓和祭祖。它通常在公历4月4日至6日之间庆祝。",
    #     "端午节是为了纪念屈原的节日，人们通常在这一天吃粽子、赛龙舟。",
    # ]
    # vector = embedding.get_embedding(model_uid="bge-large-zh-v1.5",input=content)
    # data = []
    # for index,item in enumerate(content):
    #     data.append(
    #         {
    #             "file_name": "2.docx",
    #             "file_id": "F123456789",
    #             "file_time": "2025/07/15",
    #             "number": index + 1,
    #             "content": item,
    #             "vector": vector[index],
    #         }
    #     )
    # opengauss.add_document(collection_name="test789",data=data)
    query = "中国的主要节日有哪些"
    query_vector = embedding.get_embedding(model_uid="bge-large-zh-v1.5",input=query)
    # print(f"{query_vector}\n\n\n")
    start_time = time.time()
    # filter = "file_name like '2.docx' or file_name like '3.docx'"
    filter = ""
    result = opengauss.search_by_vector(collection_name="testpy",vector=query_vector,limit=10,filter=filter)
    print(result)

    expr = f"number >= 1 and number <= 2 and file_name == '1.docx'"
    result = opengauss.query_by_scalar(collection_name="testpy",query_conditions=expr,output_fields=["content","number"])
    print(result)
    print(f"花费时间:{time.time()-start_time}")
    # print(result)
    # data= [
	# {
	# 	"file_name" : "1.docx",
	# 	"file_id" : "F123456789",
	# 	"file_time" : "2025\/07\/144465",
	# 	"number" : 1,
	# 	"content" : "中国的主要节日包括春节、清明节、端午节和中秋节。春节是中国最重要的传统节日，家家户户都会庆祝。",
	# 	"vector" : "[-0.214545656,-0.124564456,-0.037180442,0.0796617,0.011655058,0.054414865,0.018134728,-0.014711665,0.013341099,-0.01848829,-0.0029962368,-0.0026146653,0.018844409,0.022494094,0.022502296,0.03319,-0.016901912,0.003141322,0.014046893,-0.026590528,0.040023692,-0.059902202,-0.022150325,0.028232312,-0.013669211,-0.04301118,0.02208022,0.0055334414,0.026275948,0.034363553,0.016167715,0.025624035,-0.0038351954,0.016211549,0.021822177,-0.0003526786,0.031159537,0.027875787,-0.013736766,-0.004033713,0.051597036,0.00013267323,0.017304167,-0.051268067,-0.027021406,0.02952788,-0.009077424,-0.0010256862,0.0037683141,-0.029891387,0.0324233,-0.0392522,-0.02726873,-0.059244066,-0.013242465,-0.012260329,-0.022724021,-0.016988762,-0.043168478,0.011457066,-0.045087848,0.07839973,0.01268172,-0.030727956,0.019749934,0.007407636,-0.0014098028,0.016558427,0.013878814,0.049326953,0.00043359076,-0.045770008,-0.033005845,-0.034226827,0.021859193,-0.032541852,-0.0640152,-0.013741978,-0.04597532,0.0100684455,-0.0162501,0.00041677293,-0.02766743,0.017186353,0.083601035,0.020540955,0.0022602908,0.37365413,-0.010644605,-0.043077495,0.018501531,0.010425026,-0.013845851,-0.023480205,-0.005780215,0.001235898,0.031915545,-0.027120229,-0.015657337,0.0011983913,0.000849417,0.032803208,0.050984506,-0.036568593,-0.028750932,0.007014673,-0.030783199,-0.013442682,0.008141506,-0.019088026,-0.024225365,-0.05558148,-0.033669733,-0.047121458,-0.029949315,0.023132684,-0.0065868646,-0.033955805,-0.013664074,0.0478456,-0.029514158,0.014911687,-0.016390355,-0.019509709,0.03726921,0.040948186,0.019343367,-0.05906427,0.011003113,-0.0037917453,0.02627443,-0.052940074,0.040917367,-0.014772058,-0.04553716,0.041159518,-0.08367565,-0.010366637,0.0050286925,0.012909705,0.014102166,0.006273133,0.030587368,0.047009446,-0.010604246,-0.008343975,0.007901005,0.043226957,-0.057024103,0.019612798,-0.046896726,-0.013940523,0.004377543,-0.02246383,-0.0028239558,0.020098886,0.004283914,0.0026078778,0.02575615,0.012199846,-0.0017600178,-0.042587005,0.03254004,0.038789194,0.021242801,0.05594534,-0.038747616,0.038721904,0.025561096,0.055135634,0.016445331,-0.005339731,-0.017747782,-0.036731444,0.0074078194,-0.04412904,-0.011591703,-0.016667463,0.03443614,-0.0028365043,0.003152172,-0.0149684595,-0.00095531315,0.017437624,-0.015859284,0.024926536,0.041217092,-0.0020217486,-0.0069480776,0.043769676,-0.029021969,0.0008153972,-0.021974089,0.015187126,-0.01399558,-0.0038167937,-0.012813428,-0.026279958,0.0050455127,-0.013325058,0.025086889,-0.002892623,0.051714953,-0.0091603715,0.057664666,0.009207118,-0.039240975,0.04682466,0.044029772,0.029657831,-0.018329889,-0.012384374,0.015589899,-0.05215623,0.023211539,0.048837375,0.0021326793,0.024098268,-0.09007726,-0.0012828918,-0.003495399,-0.0037831133,-0.010613277,-0.069940135,0.023447586,-0.021376068,-0.0031846738,-0.027535887,-0.038443927,0.046064958,-0.024950277,-0.011131893,0.04526113,0.06677298,-0.009069438,0.025652867,0.048290204,0.0077998037,0.0067975447,-0.021308526,-0.018118136,-0.0076287207,0.011777976,-0.030544357,0.013021442,0.0048239813,0.039333317,-0.022915054,-0.018306086,0.008678163,0.013470004,-0.053561855,0.01886675,0.02086415,0.047981534,0.004880794,0.00938125,-0.018888606,-0.058856655,0.032527402,0.003874802,0.03399804,-0.016113607,-0.018318212,0.019436777,0.0042473013,-0.0113955205,-0.0056438637,-0.023020234,-0.036811523,-0.011893617,-0.008878868,0.014854666,0.036411367,-0.00735303,-0.0034074963,0.009897359,-0.037278946,0.028748928,0.0017706215,-0.03992961,0.007910021,0.00035411146,-0.049419846,-0.0061663,-0.0050084926,0.0051252604,0.039632738,-0.008061169,0.014959132,-0.012961355,0.046539,-0.02489214,-0.04555912,0.07961622,0.035469513,0.0071780453,0.0053347,0.039588824,-0.033490594,-0.01835908,0.036308065,0.016954737,0.04258934,-0.0036108978,0.015653031,0.008618069,-0.010233295,0.01869938,-0.009141138,-0.026372772,-0.005700148,0.027187455,-0.016388755,0.015841918,-0.061082046,-0.033405427,0.0340828,-0.0118797,0.0019447744,-0.042933743,0.0027397303,0.008671231,0.013267249,-0.029955268,0.03330428,0.022097375,0.04649513,-0.04865803,-0.039803814,0.05170818,-0.010929161,-0.030875135,0.038329937,0.003821337,-0.025711063,0.012211869,-0.034024723,-0.002691916,-0.024399862,0.0631818,-0.03542022,-0.023365086,-0.00072550075,-0.02862745,-0.010142776,0.011672368,-0.018359026,0.014714131,-0.03141425,-0.028108317,0.012992167,-0.0026853322,-0.000461477,0.03424473,-0.0057049496,-0.033449925,-0.023212321,-0.038653616,0.030182058,-0.06961736,0.026428422,0.0001011186,0.053891774,-0.065927215,-0.0027504587,-0.0051357467,0.004022624,-0.0055558123,-0.018613866,0.05510613,0.051852603,-0.007917943,-0.01640993,0.001748011,0.015669795,-0.009659365,0.0094794445,0.060609225,-0.030634288,0.0052940156,0.03205715,0.024902608,-0.03491183,-0.02393704,0.010905811,0.020903872,-0.040768906,-0.008453515,-0.01266024,0.0047914307,0.001598677,0.028046302,0.005459753,0.053443566,0.0040906523,-0.010998398,-0.03834163,-0.027496193,0.0051136697,-0.0035113988,0.011353025,-0.030312296,-0.028351123,0.06025463,0.013664508,0.018806102,0.015398751,-0.024032213,-0.05683225,-0.007435383,0.03130665,0.051826235,0.024824455,-0.005132256,0.010934364,-0.0010793329,0.0027310834,-0.040848747,0.0071841776,0.052963596,-0.012177516,0.01845556,-0.00052164984,0.012858056,0.027070498,0.019314224,-0.009156363,-0.041033298,-0.0059296293,0.013106406,-0.030615667,-0.011631554,0.026801068,0.018134372,-0.012602597,-0.03118147,-0.04185527,-0.045052562,-0.017960565,-0.0073317173,-0.08047153,-0.01886283,-0.01120487,-0.017697446,-0.03430537,-0.02929057,-0.0105855875,0.01057899,-0.04690063,-0.0068395804,0.015647866,-0.02196403,-0.022838851,0.0506678,-0.016567566,0.0021168732,0.02016344,0.0039348016,0.007435706,0.033788778,0.028481573,-0.047871307,0.014367726,-0.034606017,0.017989997,-0.018272659,0.041661236,-0.025678383,0.022323895,-0.022659548,-0.07091766,0.054047957,-0.01229908,-0.021690449,0.00890991,-0.013944513,-0.02491585,0.0007583694,0.00071547367,-0.012212436,0.000880128,-0.024743915,-0.023746604,0.03152886,0.030879017,-0.060603477,0.01796243,0.029766627,0.032704424,-0.013072408,-0.036892127,-0.028841943,0.04796102,-0.009533259,-0.036777016,-0.0068297563,0.022827199,-0.046758614,-0.008725522,-0.037140753,0.02465282,-0.018916242,-0.027026461,0.07357051,-0.038135886,0.008321831,-0.004846299,0.026904024,0.010515224,-0.004014718,-0.04052442,0.004730732,0.027234005,-0.0099881105,0.015510925,-0.007159468,-0.005540026,-0.02021416,-0.04427064,-0.010656281,0.015433474,0.017081512,0.012872408,-0.0047877748,-0.053059965,-0.029444955,0.003387096,-0.030435871,0.009821816,0.031505473,0.0033995677,-0.003193767,0.014475337,0.0073856246,0.008248918,-0.0012946202,-0.0044738688,-0.014364872,0.031373248,0.002278266,-0.010336799,0.029466892,0.008744488,0.01751553,0.030862868,0.033254836,-0.007514799,0.008158815,-0.0035953699,-0.034250792,0.008954552,-0.0027525683,-0.0116553,0.012074935,-0.011266517,-0.085507825,0.014128976,0.0120382905,-0.011716668,0.0076254304,0.0356921,-0.0026447503,-0.01453053,-0.023294328,0.052725278,0.005747894,-0.024340535,-0.02329437,0.057786886,-0.031663235,-0.0055880556,-0.020942673,0.030050969,0.050206885,-0.009231482,0.012888973,-0.055809718,-0.06302806,-0.024483291,0.004374613,-0.0039390665,0.065084614,-0.007945314,-0.0068797423,-0.011839018,0.010226773,0.022604302,-0.05507476,-0.020203069,0.0152610885,0.024722334,-0.00266949,-0.0063140853,-0.036682915,-0.018182322,0.015712572,-0.01377303,-0.04696967,-0.034793384,0.027193554,0.049206335,-0.05215381,0.017154096,-0.056110483,-0.04152492,-0.008265125,-0.030161642,-0.0054777763,-0.022349883,-0.035679195,0.0013813754,-0.008699279,0.030989576,0.007928983,0.026414039,-0.015822478,0.031523358,0.033709828,-0.0035792536,0.0347293,-0.047790278,-0.0133810565,-0.0244233,8.116372e-05,-0.0045449394,-0.028687607,0.0036299392,-0.029080095,-0.01601116,-0.01051632,-0.016779585,0.012762407,-0.015726643,-0.037016965,0.010773621,0.0072972802,-0.0015323494,0.012835254,-0.09709625,0.050035223,0.004498895,0.06050994,-0.004547406,-0.018627068,0.056438938,-0.03992441,-0.017349906,0.0073499233,0.0011704193,-0.011492626,0.0042544366,0.024537098,-0.020004675,0.031861342,-0.010836522,0.0059424685,-0.011656235,0.0046007275,0.004242773,0.022516394,-0.012406962,0.049013305,-0.016668642,0.015001671,0.02416423,0.036975022,0.0034204272,0.029343097,0.012571397,-0.0047638477,-0.022207597,0.05663791,0.02918036,0.0018900698,0.038119577,0.02128771,0.06734117,-0.010719028,-0.06003378,-0.04323668,-0.0071757925,-0.037661105,-0.031658314,0.028493037,0.042075247,0.011200985,0.011053499,-0.029099151,0.03223165,0.045031358,-0.026184503,0.059390098,0.011656666,-0.032701764,0.022528667,-0.0117700435,0.022002965,-0.050598405,-0.01684537,0.0465801,0.027459208,-0.00018915186,-0.017027147,-0.014186306,-0.019191703,0.04447024,0.01337335,0.017520508,-0.0027565714,-0.08254914,-0.06183202,-0.017071636,-0.037596602,0.0029635169,0.006653786,-0.011343852,0.0012271475,0.029307308,-0.015462789,-0.0032454382,0.017504686,-0.0047066538,-0.022602117,0.08577795,-0.009952142,0.0060512014,0.0421914,0.010057516,-0.021154081,0.0019251336,0.015238249,-0.004933459,0.010894134,-0.0014682265,0.025657672,0.017874394,0.024362607,0.0041748225,-0.021007393,-0.010717359,0.017068936,0.009305218,-0.026349556,0.02124688,-0.012339171,-0.01243994,-0.04603224,-0.009549604,0.02164756,-0.015809877,-0.033926472,0.02404758,-0.011821577,-0.0012149493,-0.05762148,-0.0461141,-0.02362343,-0.050604414,0.006703832,0.0023222591,-0.039670505,0.015885828,0.0006206238,0.006200438,-0.024656316,-0.018690335,0.0047896514,-0.05633691,-0.009109605,0.011775692,-0.033354808,-0.0123099405,0.0046633794,-0.025500817,-5.2282463e-05,-0.0076742563,0.007224754,0.0026106418,-0.021436412,-0.009410906,-0.055728108,-0.01947636,0.024053657,0.011026016,-0.0138932895,0.017668035,-0.04344932,-0.07836221,0.014553441,0.0015749082,0.019444613,-0.03984934,0.059159275,-0.03493033,0.0061029773,-0.03924962,0.069812275,-0.002714871,-0.014619141,-0.010644531,-0.022748683,-0.028484257,0.014925431,-0.02157648,-0.04308802,0.010579692,0.010731771,-0.06435621,-0.016734827,0.0070499345,0.017468298,0.049091004,-0.017415317,0.013188528,0.020776711,-0.017409483,-0.048719063,0.0303379,-0.007877492,-0.051356435,0.01841403,-0.008940254,-0.0041958103,0.055541925,-0.03013797,-0.0246775,-0.0354254,-0.0049215364,0.02529497,-0.0212945,-0.033164732,0.00059705786,0.013749582,-0.017635837,-0.048459772,0.015063689,0.03284191,-0.043729316,-0.024868721,0.06979662,-0.010834429,-0.029046834,-0.004970459,0.014267041,0.027662558,0.029196588,0.008610825,0.0010617878,0.005799401,-0.007504848,0.022460414,0.018897166,-0.0238412,-0.03678055,-0.08995101,0.010273596,0.05488179,-0.013547302,0.023291709,-0.071915224,0.01579441,-0.022299798,0.02084906,0.006921467,0.017523592,0.009623192,-0.019621242,0.0022384797,0.024349544,-0.022560325,0.030087532,0.025595587,0.039618045,0.025816092,0.0046026483,-0.046009924,0.00904508,0.0046925107,0.019791503,-0.00041315242,-0.051258534,0.0035131099,0.014236697,-0.002640439,-0.0129995635,-0.0028497227,0.017795637,0.007452786,0.007142696,-0.029564844,-0.006898377,-0.01544833,-0.03774736,0.024354966,0.032533284,-0.011245211,-0.04737032,-0.037770692,0.014298682,0.011139593,0.00322572,-0.0020184366,-0.027071333,0.005083079,-0.025769314,0.014817524,0.041354958,-0.010872818,-0.022590796,0.035410855,0.023967741,-0.008580868,0.017119812,-0.042981498,-0.007969874,-0.00574627,-0.0070754937,0.0024937438,0.022740316,-0.047236547,-0.042931307,0.024663953,0.056097854,-0.021225283,0.0045441403,0.021470403,0.01255903,0.014278716,0.010486409,-0.025111774,-0.015314123,0.011406065,-0.03804264,-0.044489462,-0.014139017,0.008248792,0.01764951,-0.005880838,0.0049330504,0.020075733,0.0025070824,0.037062887,0.0086542955,0.07252253,0.013402408,0.01741137,0.0006887626,-0.004689557,-0.029480956,-0.036026757,-0.010661762,-0.0060155555,-0.046290793,-0.03258077,0.0033604912,0.019728474,-0.06787419,0.007020535,0.000916477,-8.591591e-06,-0.012102421,0.0053249146,0.038110666,-0.024617514,-0.013866764,0.039139416,-0.05529589,0.01340911,-0.0067061866,0.0011127616,0.034770492,-0.0026419994,-0.027898714,-0.015918912,0.012302461,-0.015889505,0.006313616,0.030294005,-0.00791545,-0.011692794,0.0007245666,-0.012933394,0.034941737,-0.007360309,-0.008303681,-0.02046508,-0.012077987,-0.035422377,0.0008185715,0.013586146,-0.0042068935,-0.03179719,0.052093532,-0.03026564,-0.033328645,0.052147154,-0.011644953,0.044265844,-0.017049441,0.06128333,-0.028406331,0.021391228,0.061946988,-0.06548917,0.063338675,0.003762712,0.008444003,-0.0038354464,0.0022949756,0.017743532,0.030855857,0.024172058,-0.014885483,-0.026746104,0.027664946,0.0041593155,-0.01036959,0.0143544935,0.036454793,0.04214646,-0.03221009,0.02261035,-0.0055239773]",
	#     # "question": "中国的主要节日有哪些",
    #     # "source_data": [{"page":1,"Header_Footer":"头豹市场研读 | 2021/08\n中国新材料产业深度研究报告\n来源：头豹研究院\nwww.leadleo.com\n©2021 LeadLeo\n20","figure_caption":"图4: 中国新材料产业分类图谱","images_urls":["681040eadd8811e76e0d303e/image/f97b99bb-a2d2-4ee4-8ecf-6a2878982b4b.png"]}]
	# }]
    # opengauss.add_document(collection_name="testpy",data=data)
    # opengauss.update_document(collection_name="test456",data=data)
    # result = opengauss.collection_is_exists(collection_name="test2")
    # print(result)
    # opengauss.del_document(collection_name="test789",del_conditions= f"file_name == '2.docx'")
    # result = opengauss.query_by_scalar(collection_name="test789",query_conditions="number >= 1 and number <= 4 and file_name == '1.docx'",limit=5)
    # print(result)
