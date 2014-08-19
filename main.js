var child_process = require('child_process');
var express = require('express');
var sqlite3 = require('sqlite3').verbose();

var DBNAME = 'fxfdata.db';
var ALL_KEYS = ['relevance', 'text', 'actions'];
var ALL_REVISION_TYPES = ['added', 'changed', '', 'removed', ''];

var app = express();
var db;

app.set('views', __dirname + '/frontend');

app.get('/', function(req, res) {
		sites = [];

		db = new sqlite3.Database(DBNAME);
		db.serialize(function() {
				db.each('Select rowid, name From Sites', function(err, row) {
						sites.push({'id': row.rowid, 'name': row.name});
				}, function(err, nrows) { res.render('index.ejs', {'sites': sites}); });
		});
		db.close();
});

// parameters: oldVersion or newVersion = -1 indicates not to diff but just display
// oldVersion = -2 indicates to diff newVersion with the next oldest
app.get('/diff', function(req, res) {
		var site = req.query['site'];
		var fid = req.query['fixlet-id'];
		if (fid == 'None') {
				res.redirect('/site?site=' + site);
				return;
		}

		var oldVersion = -1;
		var newVersion = -1;
		if ('old-version' in req.query) {
				oldVersion = req.query['old-version'];
		}
		if ('new-version' in req.query) {
				newVersion = req.query['new-version'];
		}

		var oldContents = {'relevance': [], 'text': [], 'actions': []};
		var newContents = {'relevance': [], 'text': [], 'actions': []};
		var siteName, siteUrl, title, revisions;

		var oldId = -1;
		var newId = -1;

		revisions = [];
		title = -1;

		db = new sqlite3.Database(DBNAME);
		db.parallelize(function() {
				var statement;
				var nextFlag = false; // when oldVersion is -2, used to mark that we should compare with next oldest

				// site info
				statement = 'Select name, url From Sites Where rowid=?';
				statement = db.prepare(statement, site);
				statement.get(function(err, row) {
						siteName = row.name;
						siteUrl = row.url;
				});
				
				// table of versions
				statement = 'Select rowid, version, published, title From Revisions Where site=? and fixlet_id=? Order By version desc';
				statement = db.prepare(statement, site, fid);
				statement.each(function(err, row) {
						if (title == -1) {
								title = row.title;
						} else if (row.title != title) {
								console.log('warning: titles are different across versions');
								console.log(row.title);
								console.log(title);
								title = row.title; // default with newest title ??? TODO order?
						}
						revisions.push({'published': row.published, 'version': row.version});
						if (row.version == oldVersion || nextFlag) {
								nextFlag = false;
								oldVersion = row.version;
								oldId = row.rowid;
						}
						if (row.version == newVersion) {
								newId = row.rowid;
								if (oldVersion == -2) {
										nextFlag = true;
								}
						}
				}, function(err, nrows) { // this is in callback to serialize switch on values of old and new IDs
						if (nextFlag) { // 
								oldId = -1;
						}
						// version contents
						if (oldId != -1 && newId != -1) {
								// skip fetching directly (let the diff script do the db work)
						} else {
								if (oldId != -1) {
										statement = 'Select contents From RevisionContents Where id=?';
										statement = db.prepare(statement, oldId);
										statement.get(function (err, row) {
												oldContents = JSON.parse(row.contents);
												oldContents['text'] = [oldContents['text']]; // TODO should we move this? just makes it easier to render
										});
								} else if (newId != -1) {
										statement = 'Select contents From RevisionContents Where id=?';
										statement = db.prepare(statement, newId);
										statement.get(function (err, row) {
												newContents = JSON.parse(row.contents);
												newContents['text'] = [newContents['text']]; // TODO should we move this?
										});
								}
						}
				});
		});

		function render() {
				res.render('diff.ejs', {
						'siteId': site,
						'siteName': siteName,
						'siteUrl': siteUrl,
						'title': title,
						'revisions': revisions,
						'fixletId': fid,
						'allKeys': ALL_KEYS,
						'oldVersion': oldVersion,
						'newVersion': newVersion,
						'oldContents': oldContents,
						'newContents': newContents,
				});
		}

		db.close(function () {
				// run the diff
				if (oldId != -1 && newId != -1) {
						var command = 'python diff_service.py ' + oldId + ' ' + newId;
						console.log(command);
						child_process.exec(command, function(error, stdout, stderr) {
								var diffContents = JSON.parse(stdout);
								oldContents = diffContents[0];
								newContents = diffContents[1];
								oldContents['text'] = [oldContents['text']]; // TODO should we move this? just makes it easier to render
								newContents['text'] = [newContents['text']]; // TODO should we move this?

								ALL_KEYS.forEach(function (key) {
										if (oldContents[key] == null) {
												oldContents[key] = [];
										}
										if (newContents[key] == null) {
												newContents[key] = [];
										}
								});

								render();
						});
				} else {
						render();
				}
		});

});

app.get('/site', function(req, res) {
		var site = req.query['site'];
		var version = -1;
		if ('version' in req.query) {
				version = req.query['version'];
		}

		var revisions = {};
		var versionData = [];
		var versions = [];

		var published = -1;
		var changes = {};

		var title, siteUrl;
		
		db = new sqlite3.Database(DBNAME);
		db.parallelize(function() {
				var statement;

				// site info
				statement = 'Select name, url From Sites Where rowid=?';
				statement = db.prepare(statement, site);
				statement.get(function(err, row) {
						title = row.name;
						siteUrl = row.url;
				});

				if (version == -1) {
						// site versions
						statement = 'Select version, published, type, count(*) as affected, count(distinct published) as inconsistencies From Revisions Where site=? Group By version, type Order By version, type';
						statement = db.prepare(statement, site);

						var i = 0;
						statement.each(function(err, row) {
								i += 1;
								if (!(row.version in revisions)) {
										revisions[row.version] = {}
										console.log(i + ": " + row.inconsistencies);
										versionData.push({
												'published': row.published,
												'version': row.version,
										});
								}
								revisions[row.version][ALL_REVISION_TYPES[row.type]] = row.affected;
						});
				} else {
						// version info
						statement = 'Select fixlet_id, type, published From Revisions Where site=? And version=? Order By type, fixlet_id';
						statement = db.prepare(statement, site, version);
						statement.each(function(err, row) {
								if (!(ALL_REVISION_TYPES[row.type] in changes)) {
										changes[ALL_REVISION_TYPES[row.type]] = [];
								}
								changes[ALL_REVISION_TYPES[row.type]].push(row.fixlet_id);

								if (published != -1 && row.published != published) {
										console.log('warning: publication dates are inconsistent!');
										console.log(published);
										console.log(row.published);
								}
								published = row.published;
						});
				}
		});

		db.close(function () {
				if (version == -1) {
						versionData.forEach(function (version) {
								var affected_str = '';
								var total = 0;
								for (var type in revisions[version.version]) {
										var number = revisions[version.version][type];
										total += number;
										affected_str += ', ' + number + ' ' + type;
								}
								affected_str = total + ' (' + affected_str.substring(2) + ')';
								
								versions.push({
										'published': version.published,
										'version': version.version,
										'affected': affected_str
								});
						});
				}
				
				res.render('site.ejs', {
						'site': site,
						'title': title,
						'siteUrl': siteUrl,

						'version': version,
						'published': published,
						'changes': changes,
						'allRevisionTypes': ALL_REVISION_TYPES,

						'revisions': versions
				});
		});
				
});

app.get('/assets/:thing', function(req, res) {
		res.sendfile('frontend/assets/' + req.params.thing);
});

app.listen(8000);
