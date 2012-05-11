var mfc = {    
    initFacebook: function(event_trigger) {
	window.fbAsyncInit = function() {
	  FB.init({
	    appId      : '139767179482675', // App ID
	    channelUrl : '//www.musicfilmcomedy.com/channel.html', // Channel File
	    status     : true, // check login status
	    cookie     : true, // enable cookies to allow the server to access the session
	    xfbml      : true  // parse XFBML
	  });
	  
	  $(event_trigger).trigger("facebookReady");
	};
      
	// Load the SDK Asynchronously
	( function(d) {
	    var js, id = 'facebook-jssdk', ref = d.getElementsByTagName('script')[0];
	    if (d.getElementById(id)) {
		return;
	    }
	    
	    js = d.createElement('script'); js.id = id; js.async = true;
	    js.src = "//connect.facebook.net/en_US/all.js";
	    ref.parentNode.insertBefore(js, ref);
	 } (document) );	
    },
    
    createUserSession: function(params) {
	FB.login(function(response) {
	    if(response.authResponse) {
		var the_token = response.authResponse.accessToken;
		var user_id = response.authResponse.userID;

		FB.api('/me', { fields : 'id, name, picture, email' }, function(response) {
			if(!response || response.error) {
			    params.error();
			}
			else {
			    $.post('/create_session/', {'email' : response.email,
							'full_name': response.name,
							'fb_user_id' : user_id,
							'fb_access_token': the_token,
							'fb_picture' : response.picture })
			    .success(function() {
				params.success();
			    })
			    .error(function() {
				params.error();
			    });
			}
		    }
		);
	    }
	    else {
		params.error();
	    }
	}, { scope : 'email' });
    },
    
    loadFlickrImages: function(image_tag, query_tags, num_photos) {
	var api_key = '&api_key=da776c2b6300d481f5c23ce7bedca866';
	var tags = '&tags=' + query_tags;
	var tag_mode = '&tag_mode=all';
	var safe_search = '&safe_search=safe';
	var content_type = '&content_type=1';
	var sort = '&sort=relevance'
	var query = tags + api_key + tag_mode + safe_search + content_type + sort;
	
    $.get('http://api.flickr.com/services/rest/?method=flickr.photos.search&format=json&nojsoncallback=1' + query,
          function(response) {
              var i = 0;
              if(response) {
                  while(i < response.photos.photo.length) {
                      var farm = response.photos.photo[i].farm;
                      var server = response.photos.photo[i].server;
                      var id = response.photos.photo[i].id;
                      var secret = response.photos.photo[i].secret;

                      var img_url = 'http://farm' + farm + '.staticflickr.com/' + server + '/' + id + '_' + secret
                      var img_tag = '<a href="' + img_url + '_z.jpg" class="thumbnail"><img src="' + img_url + '_q.jpg"></img></a>'

                      $('#' + image_tag).append('<li class="span2">' + img_tag + '</li>')

                      i++;
                      if(i >= num_photos) {
                          break;
                      }
                  }
                  $(".thumbnail").colorbox({rel:'thumbnail'});
              }
          },
          'json'
         );
    },    
}
