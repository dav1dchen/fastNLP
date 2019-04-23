import os
import json
from nltk.tree import Tree

from fastNLP.core.dataset import DataSet
from fastNLP.core.instance import Instance
from fastNLP.io.file_reader import _read_csv, _read_json, _read_conll


def _download_from_url(url, path):
    from tqdm import tqdm
    import requests

    """Download file"""
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True)
    chunk_size = 16 * 1024
    total_size = int(r.headers.get('Content-length', 0))
    with open(path, "wb") as file ,\
        tqdm(total=total_size, unit='B', unit_scale=1, desc=path.split('/')[-1]) as t:
        for chunk in r.iter_content(chunk_size):
            if chunk:
                file.write(chunk)
                t.update(len(chunk))
    return

def _uncompress(src, dst):
    import zipfile, gzip, tarfile, os

    def unzip(src, dst):
        with zipfile.ZipFile(src, 'r') as f:
            f.extractall(dst)

    def ungz(src, dst):
        with gzip.open(src, 'rb') as f, open(dst, 'wb') as uf:
            length = 16 * 1024 # 16KB
            buf = f.read(length)
            while buf:
                uf.write(buf)
                buf = f.read(length)

    def untar(src, dst):
        with tarfile.open(src, 'r:gz') as f:
            f.extractall(dst)

    fn, ext = os.path.splitext(src)
    _, ext_2 = os.path.splitext(fn)
    if ext == '.zip':
        unzip(src, dst)
    elif ext == '.gz' and ext_2 != '.tar':
        ungz(src, dst)
    elif (ext == '.gz' and ext_2 == '.tar') or ext_2 == '.tgz':
        untar(src, dst)
    else:
        raise ValueError('unsupported file {}'.format(src))


class DataSetLoader:
    """所有`DataSetLoader`的接口

    """

    def load(self, path):
        """从指定 ``path`` 的文件中读取数据,返回DataSet

        :param str path: file path
        :return: a DataSet object
        """
        raise NotImplementedError

    def convert(self, data):
        """用Python数据对象创建DataSet

        :param data: inner data structure (user-defined) to represent the data.
        :return: a DataSet object
        """
        raise NotImplementedError


class PeopleDailyCorpusLoader(DataSetLoader):
    """读取人民日报数据集
    """
    def __init__(self):
        super(PeopleDailyCorpusLoader, self).__init__()
        self.pos = True
        self.ner = True

    def load(self, data_path, pos=True, ner=True):
        """

        :param str data_path: 数据路径
        :param bool pos: 是否使用词性标签
        :param bool ner: 是否使用命名实体标签
        :return: a DataSet object
        """
        self.pos, self.ner = pos, ner
        with open(data_path, "r", encoding="utf-8") as f:
            sents = f.readlines()
        examples = []
        for sent in sents:
            if len(sent) <= 2:
                continue
            inside_ne = False
            sent_pos_tag = []
            sent_words = []
            sent_ner = []
            words = sent.strip().split()[1:]
            for word in words:
                if "[" in word and "]" in word:
                    ner_tag = "U"
                    print(word)
                elif "[" in word:
                    inside_ne = True
                    ner_tag = "B"
                    word = word[1:]
                elif "]" in word:
                    ner_tag = "L"
                    word = word[:word.index("]")]
                    if inside_ne is True:
                        inside_ne = False
                    else:
                        raise RuntimeError("only ] appears!")
                else:
                    if inside_ne is True:
                        ner_tag = "I"
                    else:
                        ner_tag = "O"
                tmp = word.split("/")
                token, pos = tmp[0], tmp[1]
                sent_ner.append(ner_tag)
                sent_pos_tag.append(pos)
                sent_words.append(token)
            example = [sent_words]
            if self.pos is True:
                example.append(sent_pos_tag)
            if self.ner is True:
                example.append(sent_ner)
            examples.append(example)
        return self.convert(examples)

    def convert(self, data):
        data_set = DataSet()
        for item in data:
            sent_words = item[0]
            if self.pos is True and self.ner is True:
                instance = Instance(words=sent_words, pos_tags=item[1], ner=item[2])
            elif self.pos is True:
                instance = Instance(words=sent_words, pos_tags=item[1])
            elif self.ner is True:
                instance = Instance(words=sent_words, ner=item[1])
            else:
                instance = Instance(words=sent_words)
            data_set.append(instance)
        data_set.apply(lambda ins: len(ins["words"]), new_field_name="seq_len")
        return data_set


class ConllLoader(DataSetLoader):
    """
    读取Conll格式的数据. 数据格式详见 http://conll.cemantix.org/2012/data.html

    列号从0开始, 每列对应内容为::

        Column  Type
        0       Document ID
        1       Part number
        2       Word number
        3       Word itself
        4       Part-of-Speech
        5       Parse bit
        6       Predicate lemma
        7       Predicate Frameset ID
        8       Word sense
        9       Speaker/Author
        10      Named Entities
        11:N    Predicate Arguments
        N       Coreference

    :param headers: 每一列数据的名称，需为List or Tuple  of str。``header`` 与 ``indexs`` 一一对应
    :param indexs: 需要保留的数据列下标，从0开始。若为 ``None`` ，则所有列都保留。Default: ``None``
    :param dropna: 是否忽略非法数据，若 ``False`` ，遇到非法数据时抛出 ``ValueError`` 。Default: ``True``
    """
    def __init__(self, headers, indexs=None, dropna=True):
        super(ConllLoader, self).__init__()
        if not isinstance(headers, (list, tuple)):
            raise TypeError('invalid headers: {}, should be list of strings'.format(headers))
        self.headers = headers
        self.dropna = dropna
        if indexs is None:
            self.indexs = list(range(len(self.headers)))
        else:
            if len(indexs) != len(headers):
                raise ValueError
            self.indexs = indexs

    def load(self, path):
        ds = DataSet()
        for idx, data in _read_conll(path, indexes=self.indexs, dropna=self.dropna):
            ins = {h:data[i] for i, h in enumerate(self.headers)}
            ds.append(Instance(**ins))
        return ds


class Conll2003Loader(ConllLoader):
    """读取Conll2003数据
    
    关于数据集的更多信息,参考:
    https://sites.google.com/site/ermasoftware/getting-started/ne-tagging-conll2003-data
    """
    def __init__(self):
        headers = [
            'tokens', 'pos', 'chunks', 'ner',
        ]
        super(Conll2003Loader, self).__init__(headers=headers)


def _cut_long_sentence(sent, max_sample_length=200):
    """
    将长于max_sample_length的sentence截成多段，只会在有空格的地方发生截断。
    所以截取的句子可能长于或者短于max_sample_length

    :param sent: str.
    :param max_sample_length: int.
    :return: list of str.
    """
    sent_no_space = sent.replace(' ', '')
    cutted_sentence = []
    if len(sent_no_space) > max_sample_length:
        parts = sent.strip().split()
        new_line = ''
        length = 0
        for part in parts:
            length += len(part)
            new_line += part + ' '
            if length > max_sample_length:
                new_line = new_line[:-1]
                cutted_sentence.append(new_line)
                length = 0
                new_line = ''
        if new_line != '':
            cutted_sentence.append(new_line[:-1])
    else:
        cutted_sentence.append(sent)
    return cutted_sentence


class SSTLoader(DataSetLoader):
    """读取SST数据集, DataSet包含fields::

        words: list(str) 需要分类的文本
        target: str 文本的标签

    数据来源: https://nlp.stanford.edu/sentiment/trainDevTestTrees_PTB.zip

    :param subtree: 是否将数据展开为子树，扩充数据量. Default: ``False``
    :param fine_grained: 是否使用SST-5标准，若 ``False`` , 使用SST-2。Default: ``False``
    """
    def __init__(self, subtree=False, fine_grained=False):
        self.subtree = subtree

        tag_v = {'0':'very negative', '1':'negative', '2':'neutral',
                 '3':'positive', '4':'very positive'}
        if not fine_grained:
            tag_v['0'] = tag_v['1']
            tag_v['4'] = tag_v['3']
        self.tag_v = tag_v

    def load(self, path):
        """

        :param path: str，存储数据的路径
        :return: DataSet。
        """
        datalist = []
        with open(path, 'r', encoding='utf-8') as f:
            datas = []
            for l in f:
                datas.extend([(s, self.tag_v[t])
                              for s, t in self._get_one(l, self.subtree)])
        ds = DataSet()
        for words, tag in datas:
            ds.append(Instance(words=words, target=tag))
        return ds

    @staticmethod
    def _get_one(data, subtree):
        tree = Tree.fromstring(data)
        if subtree:
            return [(t.leaves(), t.label()) for t in tree.subtrees()]
        return [(tree.leaves(), tree.label())]


class JsonLoader(DataSetLoader):
    """
    读取json格式数据.数据必须按行存储,每行是一个包含各类属性的json对象

    :param dict fields: 需要读入的json属性名称, 和读入后在DataSet中存储的field_name
        ``fields`` 的`key`必须是json对象的属性名. ``fields`` 的`value`为读入后在DataSet存储的`field_name`,
        `value`也可为 ``None`` , 这时读入后的`field_name`与json对象对应属性同名
        ``fields`` 可为 ``None`` , 这时,json对象所有属性都保存在DataSet中. Default: ``None``
    :param bool dropna: 是否忽略非法数据,若 ``True`` 则忽略,若 ``False`` ,在遇到非法数据时,抛出 ``ValueError`` .
        Default: ``True``
    """
    def __init__(self, fields=None, dropna=False):
        super(JsonLoader, self).__init__()
        self.dropna = dropna
        self.fields = None
        self.fields_list = None
        if fields:
            self.fields = {}
            for k, v in fields.items():
                self.fields[k] = k if v is None else v
            self.fields_list = list(self.fields.keys())

    def load(self, path):
        ds = DataSet()
        for idx, d in _read_json(path, fields=self.fields_list, dropna=self.dropna):
            ins = {self.fields[k]:v for k,v in d.items()}
            ds.append(Instance(**ins))
        return ds


class SNLILoader(JsonLoader):
    """
    读取SNLI数据集，读取的DataSet包含fields::

        words1: list(str)，第一句文本, premise
        words2: list(str), 第二句文本, hypothesis
        target: str, 真实标签

    数据来源: https://nlp.stanford.edu/projects/snli/snli_1.0.zip
    """
    def __init__(self):
        fields = {
            'sentence1_parse': 'words1',
            'sentence2_parse': 'words2',
            'gold_label': 'target',
        }
        super(SNLILoader, self).__init__(fields=fields)

    def load(self, path):
        ds = super(SNLILoader, self).load(path)
        def parse_tree(x):
            t = Tree.fromstring(x)
            return t.leaves()
        ds.apply(lambda ins: parse_tree(ins['words1']), new_field_name='words1')
        ds.apply(lambda ins: parse_tree(ins['words2']), new_field_name='words2')
        ds.drop(lambda x: x['target'] == '-')
        return ds


class CSVLoader(DataSetLoader):
    """
    读取CSV格式的数据集。返回 ``DataSet``

    :param List[str] headers: CSV文件的文件头.定义每一列的属性名称,即返回的DataSet中`field`的名称
        若为 ``None`` ,则将读入文件的第一行视作 ``headers`` . Default: ``None``
    :param str sep: CSV文件中列与列之间的分隔符. Default: ","
    :param bool dropna: 是否忽略非法数据,若 ``True`` 则忽略,若 ``False`` ,在遇到非法数据时,抛出 ``ValueError`` .
        Default: ``True``
    """
    def __init__(self, headers=None, sep=",", dropna=True):
        self.headers = headers
        self.sep = sep
        self.dropna = dropna

    def load(self, path):
        ds = DataSet()
        for idx, data in _read_csv(path, headers=self.headers,
                                   sep=self.sep, dropna=self.dropna):
            ds.append(Instance(**data))
        return ds


def _add_seg_tag(data):
    """

    :param data: list of ([word], [pos], [heads], [head_tags])
    :return: list of ([word], [pos])
    """

    _processed = []
    for word_list, pos_list, _, _ in data:
        new_sample = []
        for word, pos in zip(word_list, pos_list):
            if len(word) == 1:
                new_sample.append((word, 'S-' + pos))
            else:
                new_sample.append((word[0], 'B-' + pos))
                for c in word[1:-1]:
                    new_sample.append((c, 'M-' + pos))
                new_sample.append((word[-1], 'E-' + pos))
        _processed.append(list(map(list, zip(*new_sample))))
    return _processed

